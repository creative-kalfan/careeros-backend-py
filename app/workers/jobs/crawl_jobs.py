"""ARQ background jobs for job crawling."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.services.jobs.job_ingestion_service import JobIngestionService
from app.workers.logging import JobLogger
from app.workers.registry import register_job

logger = logging.getLogger(__name__)


def _get_process_rss_mb() -> float:
    """Return process RSS memory in megabytes for telemetry."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024.0 * 1024.0)
    except Exception:
        return 0.0

# Default Adzuna query when the scheduled target's "slug" is empty.
DEFAULT_ADZUNA_QUERY = "software engineer"

# Redis key prefix for last-crawl status records (observability).
CRAWL_STATUS_PREFIX = "crawl_status"
CRAWL_STATUS_TTL_SECONDS = 7 * 24 * 3600

# Active crawl-job gauge (single event loop: plain int is sufficient).
# Surfaced in start/complete/fail logs so queue depth vs worker capacity is
# observable without a new table or metric pipeline.
_ACTIVE_CRAWLS = 0


def active_crawl_count() -> int:
    """Return the number of crawl jobs currently executing on this worker."""
    return _ACTIVE_CRAWLS


# Provider families whose discovery return is a COMPLETE inventory of that
# source (an ATS board, the YC board, or one company's careers page). For
# these, "not seen in this crawl" is strong evidence the posting disappeared,
# so the not-seen reconciliation deactivates it (Firecrawl is additionally
# scoped to the crawled careers URL).
_COMPLETE_INVENTORY_SOURCES = frozenset(
    {"greenhouse", "ashby", "lever", "smartrecruiters", "ycombinator", "workday", "icims", "firecrawl"}
)

# Query-based providers (Adzuna search, JobSpy Naukri/LinkedIn): each crawl
# exercises a bounded ROTATION of queries, never the full source inventory.
# A job absent from today's query subset is NOT evidence it disappeared —
# it simply was not requested. Applying not-seen deactivation here would
# cull otherwise-fresh jobs (observed Adzuna churn: 1066 inactive, 0 active).
# The age-based stale window (JOB_STALE_AFTER_DAYS) remains the deactivation
# boundary for these providers.
_QUERY_BASED_SOURCES = frozenset({"adzuna", "jobspy"})


def _uses_complete_inventory(source: str) -> bool:
    """True when a crawl of this source sees the whole postings inventory.

    ATS boards / YC / Firecrawl careers pages: yes (Firecrawl is scoped to
    the crawled careers URL). Query-based aggregators (Adzuna/JobSpy): no —
    not-seen never implies gone for a bounded query rotation.
    """
    return source in _COMPLETE_INVENTORY_SOURCES


def _india_only_for(source: str, slug: str) -> bool:
    """Registry-driven geographic scope for a crawl target.

    Stripe is the only greenhouse board and is registered with
    ``india_only=True``; since not-seen deactivation is scoped to
    ``source_platform="greenhouse"`` (Stripe rows only), foreign Stripe rows
    drain naturally after the next successful crawl. Unknown slugs default
    to False so ad-hoc crawls keep full-board behavior.
    """
    try:
        from app.crawlers.crawl_registry import all_targets

        return next(
            (t.india_only for t in all_targets() if t.source == source and t.slug == slug),
            False,
        )
    except Exception:
        return False


async def _record_crawl_status(
    source: str,
    slug: str,
    payload: dict[str, Any],
) -> None:
    """Best-effort: persist the last crawl run summary in Redis (7-day TTL).

    Enables the ``/dev/arq/crawl-status`` endpoint (and structured logs) to
    answer "when did this source last crawl successfully?" without a new
    database table.
    """
    try:
        from app.workers.settings import get_redis_pool

        redis = await get_redis_pool()
        key = f"{CRAWL_STATUS_PREFIX}:{source}:{slug}"
        await redis.set(key, json.dumps(payload, default=str), ex=CRAWL_STATUS_TTL_SECONDS)
    except Exception as exc:  # non-blocking observability
        logger.warning("crawl-status write failed (non-blocking): %s", exc)


def _resolve_company_scope(source: str, slug: str) -> Optional[str]:
    """Find canonical company name for scoping ATS deactivation."""
    if not slug:
        return None
    try:
        from app.crawlers.crawl_registry import all_targets

        target = next((t for t in all_targets() if t.source == source and t.slug == slug), None)
        if target and target.company:
            return target.company
    except Exception:
        pass
    if "|" in slug:
        company_part, _, _ = slug.partition("|")
        if company_part:
            return company_part
    return slug.replace("-", " ").title()


def _deactivate_after_success(
    ingestion: Any,
    source: str,
    slug: str,
    crawl_started_at: str,
    max_age_days: int,
    cancel_event: Optional[threading.Event] = None,
    timeout_seconds: float = 45.0,
    already_gated: bool = False,
    miss_threshold: int = 2,
) -> tuple[int, int, int, int]:
    """Synchronous post-ingestion deactivation; runs in a worker thread.

    Ordering is load-bearing and preserved exactly: not-seen reconciliation
    first (complete-inventory sources only), then the age-based staleness
    backstop for all providers. Raises on DB errors so the caller keeps the
    existing best-effort warning behavior. Supports cancellation tokens and
    timeout bounds.

    Ownership rule: the production caller holds ``async_persistence_slot``
    and passes ``already_gated=True`` so the pair runs via
    ``run_gated_persistence`` WITHOUT re-acquiring the sync capacity
    semaphore (single-gate). Direct/legacy callers keep the default
    ``already_gated=False`` and remain protected by ``call_serialized``.
    Thread-safety in both cases rests on thread-local Supabase clients.
    """
    from app.db.supabase import call_serialized, run_gated_persistence

    not_seen_kwargs: dict[str, Any] = {"miss_threshold": miss_threshold}
    stale_kwargs: dict[str, Any] = {}

    if source == "firecrawl":
        company, _, careers_url_scope = slug.partition("|")
        if careers_url_scope:
            not_seen_kwargs["careers_url"] = careers_url_scope
            stale_kwargs["careers_url"] = careers_url_scope
        if company:
            not_seen_kwargs["company"] = company
            stale_kwargs["company"] = company
    elif source in ("ashby", "greenhouse", "lever", "smartrecruiters"):
        # Single-board ATS sources: scope reconciliation to this company
        company = _resolve_company_scope(source, slug)
        if company:
            not_seen_kwargs["company"] = company
            stale_kwargs["company"] = company

    def _run() -> tuple[int, int, int, int]:
        not_seen_start = time.monotonic()
        if _uses_complete_inventory(source):
            not_seen = ingestion.job_repository.deactivate_not_seen_since(
                source_platform=source,
                since_iso=crawl_started_at,
                cancel_event=cancel_event,
                **not_seen_kwargs,
            )
        else:
            logger.info(
                "Skipping not-seen deactivation for %s (query-based provider: "
                "today's bounded query rotation is not the full inventory)",
                source,
            )
            not_seen = 0
        not_seen_ms = int((time.monotonic() - not_seen_start) * 1000)

        stale_start = time.monotonic()
        stale = ingestion.job_repository.deactivate_stale_jobs(
            source_platform=source,
            max_age_days=max_age_days,
            cancel_event=cancel_event,
            **stale_kwargs,
        )
        stale_ms = int((time.monotonic() - stale_start) * 1000)
        return not_seen, stale, not_seen_ms, stale_ms

    if already_gated:
        return run_gated_persistence(
            _run, cancel_event=cancel_event, timeout_seconds=timeout_seconds
        )
    return call_serialized(
        _run, cancel_event=cancel_event, timeout_seconds=timeout_seconds
    )


async def _dispatch_ingest(
    fn: Any, *args: Any, cancel_event: Optional[threading.Event] = None, **kwargs: Any
) -> Any:
    """Invoke an ingestion method, forwarding cancel_event and kwargs if accepted."""
    call_kwargs = dict(kwargs)
    if cancel_event is not None:
        call_kwargs["cancel_event"] = cancel_event
    try:
        return await fn(*args, **call_kwargs)
    except TypeError:
        try:
            return await fn(*args, **kwargs)
        except TypeError:
            return await fn(*args)


@register_job(
    "crawl_company_job",
    timeout=300,
    max_tries=3,
    retry=True,
    description="Crawl jobs for a single ATS source/company.",
)
async def crawl_company_job(ctx: dict[str, Any], source: str, slug: str) -> dict[str, Any]:
    """Crawl jobs for a single ATS source/company.

    Payload:
        {
            "source": "ashby" | "greenhouse" | "smartrecruiters" | "lever" | "adzuna" | "jobspy" | "ycombinator" | "firecrawl",
            "slug": "notion"  # for adzuna/jobspy: the search query (optional)
        }

    Reliability behavior:
        - Failures propagate to ARQ for retry (max_tries=2); nothing is
          deactivated or deleted on failure.
        - After a SUCCESSFUL persistence pass, jobs from this source that have
          not been seen for a full freshness window are deactivated
          (NO LONGER SEEN -> INACTIVE; never deleted). Deactivation is scoped
          to this source so one source cannot deactivate another's jobs.
        - One JobIngested domain event is published per successful run via the
          in-process event bus. Handler failures are isolated by the bus and
          never fail the crawl.
    """
    global _ACTIVE_CRAWLS
    job_id: str = ctx.get("job_id", "unknown")
    job_logger = JobLogger(job_id=job_id, job_type="crawl_company", source=source, slug=slug)
    job_start = time.monotonic()
    # Wall-clock crawl start: the staleness reconciliation boundary. Jobs
    # last seen BEFORE this instant were not observed by this crawl.
    crawl_started_at = datetime.now(timezone.utc).isoformat()
    cancel_event = threading.Event()

    current_phase = "init"
    provider_ms = 0
    deactivated_not_seen = 0
    deactivated = 0
    deactivate_not_seen_ms = 0
    deactivate_stale_ms = 0
    deactivation_total_ms = 0
    result: dict[str, Any] = {}

    _ACTIVE_CRAWLS += 1
    job_logger.started()
    logger.info(
        "crawl started active_crawls=%d source=%s slug=%s threads=%d rss_mb=%.1f",
        _ACTIVE_CRAWLS,
        source,
        slug,
        threading.active_count(),
        _get_process_rss_mb(),
    )

    ingestion = JobIngestionService()

    try:
        current_phase = "provider_discovery"
        provider_start = time.monotonic()
        if source == "ashby":
            result = await _dispatch_ingest(ingestion.ingest_ashby_jobs, slug, cancel_event=cancel_event)
        elif source == "greenhouse":
            result = await _dispatch_ingest(
                ingestion.ingest_greenhouse_jobs,
                slug,
                india_only=_india_only_for(source, slug),
                cancel_event=cancel_event,
            )
        elif source == "smartrecruiters":
            result = await _dispatch_ingest(
                ingestion.ingest_smartrecruiters_jobs, slug, cancel_event=cancel_event
            )
        elif source == "lever":
            result = await _dispatch_ingest(
                ingestion.ingest_lever_jobs, slug, cancel_event=cancel_event
            )
        elif source == "adzuna":
            result = await _dispatch_ingest(
                ingestion.ingest_adzuna_jobs,
                slug or DEFAULT_ADZUNA_QUERY,
            )
        elif source == "jobspy":
            result = await _dispatch_ingest(
                ingestion.ingest_jobspy_scheduled,
                extra_query=slug or None,
            )
        elif source == "ycombinator":
            result = await _dispatch_ingest(
                ingestion.ingest_ycombinator_jobs,
                cancel_event=cancel_event,
            )
        elif source == "firecrawl":
            company, _, careers_url = slug.partition("|")
            if not careers_url:
                raise ValueError("firecrawl crawl requires slug '<company>|<careers_url>'")
            result = await _dispatch_ingest(
                ingestion.ingest_generic_career_page,
                careers_url=careers_url,
                company=company or None,
                cancel_event=cancel_event,
            )
        else:
            raise ValueError(f"Unknown source: {source}")

        provider_ms = int((time.monotonic() - provider_start) * 1000)
        inserted_ids = getattr(ingestion.job_repository, "last_inserted_ids", [])
        if not isinstance(inserted_ids, list):
            inserted_ids = []
        if not inserted_ids:
            inserted_ids = result.get("inserted_ids", [])
        if not isinstance(inserted_ids, list):
            inserted_ids = []
        content_hash = getattr(ingestion.job_repository, "last_content_hash", None)
        logger.info(
            "crawl provider_ms=%d phase=discover_normalize source=%s slug=%s "
            "discovered=%d",
            provider_ms, source, slug, result.get("discovered", 0),
        )

        current_phase = "deactivation"
        deact_async_wait_ms = 0
        deact_async_hold_ms = 0
        deact_to_thread_ms = 0
        
        discovered = result.get("discovered", 0)
        try:
            prev_active_res = ingestion.job_repository._client.table("jobs").select("id", count="exact").eq("is_active", True).eq("source_platform", source).execute()
            count_val = getattr(prev_active_res, "count", 0)
            prev_active_count = int(count_val) if isinstance(count_val, (int, float)) else 0
        except Exception:
            prev_active_count = 0
            
        is_suspicious_empty = False
        if discovered == 0 and prev_active_count > 0:
            is_suspicious_empty = True
        elif discovered < (prev_active_count * 0.5) and prev_active_count > 10:
            is_suspicious_empty = True
            
        if is_suspicious_empty:
            logger.warning("Suspicious empty crawl for %s:%s (discovered=%d, prev_active=%d). Skipping deactivation.", source, slug, discovered, prev_active_count)
            result["status"] = "suspicious_empty"
        else:
            try:
                from app.config import get_settings
                from app.db.supabase import async_persistence_slot

                max_age_days = get_settings().job_stale_after_days
                deact_start = time.monotonic()
                deact_async_acquire_start = time.monotonic()
                async with async_persistence_slot(cancel_event=cancel_event, timeout_seconds=45.0):
                    deact_async_wait_ms = int((time.monotonic() - deact_async_acquire_start) * 1000)
                    deact_hold_start = time.monotonic()
                    deact_thread_start = time.monotonic()
                    deactivated_not_seen, deactivated, deactivate_not_seen_ms, deactivate_stale_ms = await asyncio.to_thread(
                        _deactivate_after_success,
                        ingestion,
                        source,
                        slug,
                        crawl_started_at,
                        max_age_days,
                        cancel_event,
                        45.0,
                        True,
                        get_settings().job_miss_threshold,
                    )
                    deact_to_thread_ms = int((time.monotonic() - deact_thread_start) * 1000)
                    deact_async_hold_ms = int((time.monotonic() - deact_hold_start) * 1000)
                deactivation_total_ms = int((time.monotonic() - deact_start) * 1000)
            except Exception as exc:
                logger.warning(
                    "Stale deactivation skipped (non-blocking): source=%s error=%s", source, exc
                )

        from app.db.supabase import persistence_gate_snapshot
        gate = persistence_gate_snapshot()
        
        logger.info(
            "CRAWL_FINISHED phase=completed source=%s slug=%s job_try=%d fetch_ms=%d persist_wait_ms=%d persist_hold_ms=%d total_ms=%d path=%s discovered=%d inserted=%d updated=%d unchanged=%d deactivated=%d rss_mb=%.1f",
            source, slug, ctx.get("job_try", 1), provider_ms, result.get("async_wait_ms", 0), result.get("async_hold_ms", 0), int((time.monotonic() - job_start) * 1000), result.get("path", "legacy"), discovered, result.get("inserted", 0), result.get("updated", 0), result.get("unchanged", 0), deactivated_not_seen + deactivated, _get_process_rss_mb()
        )

        from app.services.jobs.crawl_dispatcher import complete_target
        await complete_target(
            source, slug, True,
            job_count=int(discovered),
            content_hash=content_hash,
        )

        current_phase = "event_dispatch"
        try:
            from app.events import JobIngested, get_event_bus
            for external_id in inserted_ids:
                await get_event_bus().publish(JobIngested(
                    aggregate_id=f"{source}:{external_id}",
                    source_platform=source,
                    jobs_processed=1,
                    metadata={"external_job_id": external_id, "inserted": True},
                ))
                try:
                    from app.workers.settings import get_redis_pool
                    redis = await get_redis_pool()
                    import hashlib
                    analysis_id = "analyze:" + hashlib.sha1(f"{source}:{external_id}".encode()).hexdigest()
                    await redis.enqueue_job("analyze_job_intelligence", external_id, _job_id=analysis_id)
                except Exception as exc:
                    logger.warning("new-job analysis enqueue failed (%s)", type(exc).__name__)
            if not inserted_ids and int(result.get("inserted", 0)) > 0:
                # Compatibility for alternate repositories without ID side-channel.
                await get_event_bus().publish(JobIngested(
                    aggregate_id=f"{source}:{slug}", source_platform=source,
                    jobs_processed=int(result.get("inserted", 0)),
                    metadata={"inserted": True, "identity_unavailable": True},
                ))
        except Exception as exc:
            logger.warning("Event Bus publish failed (non-blocking): %s", exc)

        current_phase = "completed"
        duration_ms = int((time.monotonic() - job_start) * 1000)
        job_logger.completed(
            duration_ms=duration_ms,
            discovered=result.get("discovered", 0),
            inserted=result.get("inserted", 0),
            updated=result.get("updated", 0),
            unchanged=result.get("unchanged", 0),
            deduplicated=result.get("deduplicated", 0),
            skipped=result.get("skipped", 0),
            deactivated=deactivated + deactivated_not_seen,
            provider_ms=provider_ms,
            active_crawls=max(0, _ACTIVE_CRAWLS - 1),
        )

        current_phase = "status_record"
        await _record_crawl_status(
            source,
            slug,
            {
                "source": source,
                "slug": slug,
                "status": result.get("status", "success"),
                "phase": current_phase,
                "started_at": crawl_started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": duration_ms,
                "discovered": result.get("discovered", 0),
                "inserted": result.get("inserted", 0),
                "updated": result.get("updated", 0),
                "unchanged": result.get("unchanged", 0),
                "deduplicated": result.get("deduplicated", 0),
                "skipped": result.get("skipped", 0),
                "deactivated": deactivated_not_seen + deactivated,
                "deactivated_not_seen": deactivated_not_seen,
                "deactivated_stale": deactivated,
                "provider_ms": provider_ms,
                "upsert_ms": result.get("upsert_ms", 0),
                "deactivation_total_ms": deactivation_total_ms,
            },
        )

        return {
            "success": True,
            "status": result.get("status", "success"),
            "source": source,
            "slug": slug,
            "result": result,
            "deactivated": deactivated_not_seen + deactivated,
            "deactivated_not_seen": deactivated_not_seen,
            "duration_ms": duration_ms,
            "discovered": result.get("discovered", 0),
            "inserted": result.get("inserted", 0),
            "updated": result.get("updated", 0),
            "unchanged": result.get("unchanged", 0),
            "deduplicated": result.get("deduplicated", 0),
            "skipped": result.get("skipped", 0),
        }

    except asyncio.CancelledError:
        cancel_event.set()
        duration_ms = int((time.monotonic() - job_start) * 1000)
        from app.db.supabase import persistence_gate_snapshot
        gate = persistence_gate_snapshot()
        logger.warning(
            "crawl cancelled=true phase=%s active_crawls=%d source=%s slug=%s "
            "duration_ms=%d provider_ms=%d threads=%d rss_mb=%.1f "
            "persistence_waiters=%d persistence_holders=%d "
            "async_waiting=%d async_holding=%d sync_waiting=%d sync_holding=%d",
            current_phase,
            _ACTIVE_CRAWLS,
            source,
            slug,
            duration_ms,
            provider_ms,
            threading.active_count(),
            _get_process_rss_mb(),
            int(gate.get("persistence_waiters", 0)),
            int(gate.get("persistence_holders", 0)),
            int(gate.get("async_waiting_now", 0)),
            int(gate.get("async_holding_now", 0)),
            int(gate.get("sync_waiting_now", 0)),
            int(gate.get("sync_holding_now", 0)),
        )
        await _record_crawl_status(
            source,
            slug,
            {
                "source": source,
                "slug": slug,
                "status": "cancelled",
                "phase": current_phase,
                "started_at": crawl_started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": duration_ms,
            },
        )
        raise
    except Exception as exc:
        cancel_event.set()
        duration_ms = int((time.monotonic() - job_start) * 1000)
        try:
            from app.services.jobs.crawl_dispatcher import complete_target
            await complete_target(
                source, slug, False, error=type(exc).__name__,
                not_found=type(exc).__name__ == "BoardNotFoundError",
            )
        except Exception:
            logger.warning("crawl target failure update failed", exc_info=True)
        from app.db.supabase import PersistenceTimeoutError
        from arq import Retry
        if isinstance(exc, PersistenceTimeoutError):
            logger.error("Persistence timeout in phase=%s for %s:%s. Retrying.", current_phase, source, slug)
            raise Retry(defer=ctx.get("job_try", 1) * 30)

        job_logger.failed(duration_ms=duration_ms, error_type=exc.__class__.__name__)
        from app.db.supabase import persistence_gate_snapshot
        gate = persistence_gate_snapshot()
        logger.error(
            "crawl failed phase=%s active_crawls=%d source=%s slug=%s "
            "duration_ms=%d error=%s: %s threads=%d rss_mb=%.1f "
            "persistence_waiters=%d persistence_holders=%d "
            "async_waiting=%d async_holding=%d sync_waiting=%d sync_holding=%d",
            current_phase,
            _ACTIVE_CRAWLS,
            source,
            slug,
            duration_ms,
            exc.__class__.__name__,
            exc,
            threading.active_count(),
            _get_process_rss_mb(),
            int(gate.get("persistence_waiters", 0)),
            int(gate.get("persistence_holders", 0)),
            int(gate.get("async_waiting_now", 0)),
            int(gate.get("async_holding_now", 0)),
            int(gate.get("sync_waiting_now", 0)),
            int(gate.get("sync_holding_now", 0)),
        )
        await _record_crawl_status(
            source,
            slug,
            {
                "source": source,
                "slug": slug,
                "status": "failed",
                "phase": current_phase,
                "started_at": crawl_started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": duration_ms,
                "error": f"{exc.__class__.__name__}: {exc}",
            },
        )
        raise
    finally:
        cancel_event.set()
        _ACTIVE_CRAWLS = max(0, _ACTIVE_CRAWLS - 1)
        try:
            from app.workers.settings import get_redis_pool
            redis = await get_redis_pool()
            lock_key = f"crawl_lock:{source}:{slug}"
            lock_val = await redis.get(lock_key)
            if lock_val and lock_val.decode("utf-8") == ctx.get("job_id"):
                await redis.delete(lock_key)
        except Exception:
            pass
        logger.info(
            "crawl finished active_crawls=%d source=%s slug=%s threads=%d rss_mb=%.1f",
            _ACTIVE_CRAWLS,
            source,
            slug,
            threading.active_count(),
            _get_process_rss_mb(),
        )

