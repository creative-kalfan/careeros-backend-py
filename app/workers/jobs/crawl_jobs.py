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
) -> tuple[int, int, int, int]:
    """Synchronous post-ingestion deactivation; runs in a worker thread.

    Ordering is load-bearing and preserved exactly: not-seen reconciliation
    first (complete-inventory sources only), then the age-based staleness
    backstop for all providers. Raises on DB errors so the caller keeps the
    existing best-effort warning behavior. The whole pair runs under the
    shared-client lock so executor threads never drive the client concurrently.
    Supports cancellation tokens and timeout bounds.
    """
    from app.db.supabase import call_serialized

    not_seen_kwargs: dict[str, Any] = {}
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

    return call_serialized(
        _run, cancel_event=cancel_event, timeout_seconds=timeout_seconds
    )


async def _dispatch_ingest(
    fn: Any, *args: Any, cancel_event: Optional[threading.Event] = None, **kwargs: Any
) -> Any:
    """Invoke an ingestion method, forwarding cancel_event if accepted."""
    try:
        return await fn(*args, cancel_event=cancel_event, **kwargs)
    except TypeError:
        return await fn(*args, **kwargs)


@register_job(
    "crawl_company_job",
    timeout=300,
    max_tries=2,
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
                cancel_event=cancel_event,
            )
        elif source == "jobspy":
            # Broad discovery layer: bounded rotation batch (query families
            # x India locations x freshness buckets) with provider-aware
            # throttling. The registry slug rides along as one extra query.
            result = await _dispatch_ingest(
                ingestion.ingest_jobspy_scheduled,
                extra_query=slug or None,
                cancel_event=cancel_event,
            )
        elif source == "ycombinator":
            result = await _dispatch_ingest(
                ingestion.ingest_ycombinator_jobs, cancel_event=cancel_event
            )
        elif source == "firecrawl":
            # Slug format: "<company>|<careers_url>" (careers URL is required).
            # Generic career page: Crawl4AI primary, Firecrawl fallback
            # (see app.crawlers.generic_fallback). Direct ATS sources above
            # always keep priority over both generic providers.
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
        logger.info(
            "crawl provider_ms=%d phase=discover_normalize source=%s slug=%s "
            "discovered=%d",
            provider_ms, source, slug, result.get("discovered", 0),
        )

        current_phase = "deactivation"
        deact_async_wait_ms = 0
        deact_async_hold_ms = 0
        deact_to_thread_ms = 0
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
                    cancel_event=cancel_event,
                    timeout_seconds=45.0,
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
            "production_timing crawl_source=%s crawl_slug=%s provider_ms=%d upsert_ms=%d "
            "persistence_wait_ms=%d persistence_hold_ms=%d deactivate_not_seen_ms=%d "
            "deactivate_stale_ms=%d deactivation_total_ms=%d db_requests=%d "
            "persistence_waiters=%d persistence_holders=%d "
            "async_wait_ms=%d async_hold_ms=%d deact_async_wait_ms=%d deact_async_hold_ms=%d "
            "deact_to_thread_ms=%d async_waiting=%d async_holding=%d sync_waiting=%d sync_holding=%d",
            source,
            slug,
            provider_ms,
            result.get("upsert_ms", 0),
            result.get("persistence_wait_ms", 0),
            result.get("persistence_hold_ms", 0),
            deactivate_not_seen_ms,
            deactivate_stale_ms,
            deactivation_total_ms,
            getattr(ingestion.job_repository, "last_db_requests", -1),
            int(gate.get("persistence_waiters", 0)),
            int(gate.get("persistence_holders", 0)),
            int(result.get("async_wait_ms", 0)),
            int(result.get("async_hold_ms", 0)),
            deact_async_wait_ms,
            deact_async_hold_ms,
            deact_to_thread_ms,
            int(gate.get("async_waiting_now", 0)),
            int(gate.get("async_holding_now", 0)),
            int(gate.get("sync_waiting_now", 0)),
            int(gate.get("sync_holding_now", 0)),
        )

        # Event Bus integration: one JobIngested per successful ingestion run.
        # Published AFTER persistence succeeds; never on failed crawls.
        current_phase = "event_dispatch"
        try:
            from app.events import JobIngested, get_event_bus

            report = await get_event_bus().publish(
                JobIngested(
                    aggregate_id=f"{source}:{slug}" if slug else source,
                    source_platform=source,
                    jobs_processed=int(result.get("discovered", 0)),
                    metadata={
                        "inserted": result.get("inserted", 0),
                        "updated": result.get("updated", 0),
                        "unchanged": result.get("unchanged", 0),
                        "deactivated": deactivated,
                    },
                ),
                context=None,  # system-scoped operation; no user RLS context
            )
            if not report.succeeded:
                logger.warning(
                    "JobIngested dispatch had handler failures: %s",
                    [f.error for f in report.failures],
                )
        except Exception as exc:
            logger.warning("JobIngested publish failed (non-blocking): %s", exc)

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

        # Observability: persist the last crawl run summary (successful crawl).
        current_phase = "status_record"
        await _record_crawl_status(
            source,
            slug,
            {
                "source": source,
                "slug": slug,
                "status": "success",
                "started_at": crawl_started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": duration_ms,
                "discovered": result.get("discovered", 0),
                "inserted": result.get("inserted", 0),
                "updated": result.get("updated", 0),
                "unchanged": result.get("unchanged", 0),
                "deduplicated": result.get("deduplicated", 0),
                "skipped": result.get("skipped", 0),
                "deactivated_not_seen": deactivated_not_seen,
                "deactivated_stale": deactivated,
            },
        )

        return {
            "success": True,
            "source": source,
            "slug": slug,
            "result": result,
            "deactivated": deactivated + deactivated_not_seen,
            "deactivated_not_seen": deactivated_not_seen,
            "duration_ms": duration_ms,
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
        logger.info(
            "crawl finished active_crawls=%d source=%s slug=%s threads=%d rss_mb=%.1f",
            _ACTIVE_CRAWLS,
            source,
            slug,
            threading.active_count(),
            _get_process_rss_mb(),
        )
