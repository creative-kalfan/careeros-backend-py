"""ARQ background jobs for job crawling."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.services.jobs.job_ingestion_service import JobIngestionService
from app.workers.logging import JobLogger
from app.workers.registry import register_job

logger = logging.getLogger(__name__)

# Default Adzuna query when the scheduled target's "slug" is empty.
DEFAULT_ADZUNA_QUERY = "software engineer"

# Redis key prefix for last-crawl status records (observability).
CRAWL_STATUS_PREFIX = "crawl_status"
CRAWL_STATUS_TTL_SECONDS = 7 * 24 * 3600

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
    job_id: str = ctx.get("job_id", "unknown")
    job_logger = JobLogger(job_id=job_id, job_type="crawl_company", source=source, slug=slug)
    job_start = time.monotonic()
    # Wall-clock crawl start: the staleness reconciliation boundary. Jobs
    # last seen BEFORE this instant were not observed by this crawl.
    crawl_started_at = datetime.now(timezone.utc).isoformat()

    job_logger.started()

    ingestion = JobIngestionService()

    try:
        if source == "ashby":
            result = await ingestion.ingest_ashby_jobs(slug)
        elif source == "greenhouse":
            result = await ingestion.ingest_greenhouse_jobs(
                slug, india_only=_india_only_for(source, slug)
            )
        elif source == "smartrecruiters":
            result = await ingestion.ingest_smartrecruiters_jobs(slug)
        elif source == "lever":
            result = await ingestion.ingest_lever_jobs(slug)
        elif source == "adzuna":
            result = await ingestion.ingest_adzuna_jobs(slug or DEFAULT_ADZUNA_QUERY)
        elif source == "jobspy":
            result = await ingestion.ingest_jobspy_jobs(slug or "data analyst India")
        elif source == "ycombinator":
            result = await ingestion.ingest_ycombinator_jobs()
        elif source == "firecrawl":
            # Slug format: "<company>|<careers_url>" (careers URL is required).
            company, _, careers_url = slug.partition("|")
            if not careers_url:
                raise ValueError("firecrawl crawl requires slug '<company>|<careers_url>'")
            result = await ingestion.ingest_firecrawl_jobs(
                careers_url=careers_url, company=company or None
            )
        else:
            raise ValueError(f"Unknown source: {source}")
    except Exception as exc:
        duration_ms = int((time.monotonic() - job_start) * 1000)
        job_logger.failed(duration_ms=duration_ms, error_type=exc.__class__.__name__)
        # Crawl FAILED: record failure, keep previous jobs active, deactivate NOTHING.
        await _record_crawl_status(
            source,
            slug,
            {
                "source": source,
                "slug": slug,
                "status": "failed",
                "started_at": crawl_started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": duration_ms,
                "error": f"{exc.__class__.__name__}: {exc}",
            },
        )
        raise

    # Lifecycle hygiene (successful crawls only):
    #   1. NO-LONGER-SEEN reconciliation: jobs from this source not observed
    #      since crawl_started_at are deactivated — but ONLY for providers
    #      whose crawl sees the complete inventory (ATS boards / YC). Firecrawl
    #      is additionally narrowed to the crawled careers URL so one company's
    #      success can never deactivate another company's jobs. Query-based
    #      aggregators (Adzuna/JobSpy) are EXEMPT: today's query rotation not
    #      containing a job is not evidence the job disappeared.
    #   2. Age-based staleness (JOB_STALE_AFTER_DAYS) as a final backstop (all
    #      providers, including query-based ones).
    # Best-effort: never fails the crawl.
    deactivated_not_seen = 0
    deactivated = 0
    try:
        from app.config import get_settings

        not_seen_kwargs: dict[str, Any] = {}
        if source == "firecrawl":
            _, _, careers_url_scope = slug.partition("|")
            not_seen_kwargs["careers_url"] = careers_url_scope
        if _uses_complete_inventory(source):
            deactivated_not_seen = ingestion.job_repository.deactivate_not_seen_since(
                source_platform=source,
                since_iso=crawl_started_at,
                **not_seen_kwargs,
            )
        else:
            logger.info(
                "Skipping not-seen deactivation for %s (query-based provider: "
                "today's bounded query rotation is not the full inventory)",
                source,
            )
        deactivated = ingestion.job_repository.deactivate_stale_jobs(
            source_platform=source,
            max_age_days=get_settings().job_stale_after_days,
        )
    except Exception as exc:
        logger.warning(
            "Stale deactivation skipped (non-blocking): source=%s error=%s", source, exc
        )

    # Event Bus integration: one JobIngested per successful ingestion run.
    # Published AFTER persistence succeeds; never on failed crawls.
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
    )

    # Observability: persist the last crawl run summary (successful crawl).
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
