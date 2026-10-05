"""Job ingestion service: orchestrates the full job ingestion pipeline."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from app.crawlers.adapters.ashby import AshbyAdapter
from app.crawlers.adapters.greenhouse import GreenhouseAdapter
from app.crawlers.adapters.lever import LeverAdapter
from app.crawlers.adapters.smartrecruiters import SmartRecruitersAdapter
from app.crawlers.source_quality import classify_source
from app.crawlers.aggregators.adzuna import AdzunaAdapter
from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository
from app.services.jobs.job_service import JobService

# Deterministic broad-query rotation for Adzuna (India-first, bounded).
# One batch of ADZUNA_BATCH_SIZE queries is exercised per crawl cycle,
# rotating by day-of-year so coverage is deterministic and restart-safe.
# The matrix covers the task §5 priority domains (data analytics, BI, data
# engineering, AI/ML, backend, software engineering, SAP, risk & financial
# analytics) plus the city-scoped queries that live probes showed to be
# GENUINELY incremental (unique India jobs beyond the role+India baseline —
# see scripts/probe_adzuna_city_yield.py). Budget: batch is bounded and the
# rotation cycles over this matrix within the staleness window.
ADZUNA_BROAD_QUERIES = [
    # Batch 1 (Day % 13 == 0)
    "data analyst India",
    "data engineer India",
    "software engineer India",
    # Batch 2 (Day % 13 == 1)
    "business analyst India",
    "machine learning India",
    "SAP India",
    # Batch 3 (Day % 13 == 2)
    "data analytics India",
    "backend engineer India",
    "AI engineer India",
    # Batch 4 (Day % 13 == 3)
    "BI analyst India",
    "data engineering India",
    "SAP ABAP India",
    # Batch 5 (Day % 13 == 4)
    "reporting analyst India",
    "analytics engineer India",
    "artificial intelligence India",
    # Batch 6 (Day % 13 == 5)
    "business intelligence India",
    "Python backend India",
    "ABAP developer India",
    # Batch 7 (Day % 13 == 6)
    "risk analyst India",
    "ETL developer India",
    "data scientist India",
    # Batch 8 (Day % 13 == 7)
    "financial analyst India",
    "Java backend India",
    "SAP HANA India",
    # Batch 9 (Day % 13 == 8)
    "risk analytics India",
    "data warehouse India",
    "generative AI India",
    # Batch 10 (Day % 13 == 9)
    "data analyst Bengaluru",
    "software engineer Bengaluru",
    "API developer India",
    # Batch 11 (Day % 13 == 10)
    "data analyst Hyderabad",
    "software engineer Hyderabad",
    "data engineer Bengaluru",
    # Batch 12 (Day % 13 == 11)
    "data analyst Pune",
    "software engineer Pune",
    "data analyst Mumbai",
    # Batch 13 (Day % 18 == 12)
    "data analyst Chennai",
    "software engineer Chennai",
    "data analyst Gurugram",
    # Batch 14: Fresher Data Engineering (Day % 18 == 13)
    "junior data engineer India",
    "fresher data engineer India",
    "graduate data engineer India",
    # Batch 15: Fresher SAP / ERP (Day % 18 == 14)
    "SAP fresher India",
    "junior SAP India",
    "entry level SAP India",
    # Batch 16: Fresher Analytics / BI (Day % 18 == 15)
    "junior data analyst India",
    "fresher data analyst India",
    "graduate data analyst India",
    # Batch 17: Fresher Backend (Day % 18 == 16)
    "junior backend engineer India",
    "fresher backend developer India",
    "graduate backend developer India",
    # Batch 18: Fresher AI / ML & Trainees (Day % 18 == 17)
    "junior machine learning engineer India",
    "fresher AI engineer India",
    "trainee data engineer India",
]
ADZUNA_BATCH_SIZE = 3
# Broad rotation is India-scoped only; the primary query already covers
# remote/global. Keeps the free-tier budget bounded (primary 3 + batch 3 =
# ~6 calls/crawl/day, ~180/mo, well inside the ~1000/mo free allowance).
ADZUNA_BROAD_COUNTRIES = ("in",)

logger = logging.getLogger(__name__)


class JobIngestionService:
    """Orchestrates the job ingestion pipeline."""

    def __init__(
        self,
        job_repository: Optional[JobRepository] = None,
        job_service: Optional[JobService] = None,
    ) -> None:
        self.job_repository = job_repository or JobRepository()
        self.job_service = job_service or JobService()
        self.last_persistence_metrics: dict[str, int] = {}

    async def _persist_offloop(
        self,
        normalized_jobs: list,
        source: Optional[str] = None,
        slug: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        timeout_seconds: float = 75.0,
    ) -> dict[str, Any]:
        """Run the synchronous Supabase upsert off the event loop with cancellation and timeouts.

        ``upsert_jobs`` issues blocking HTTP calls (one bulk existence fetch
        per platform chunk + bulk writes). Awaiting it directly stalls ARQ
        polling, Redis I/O, and APScheduler on the shared worker loop;
        ``to_thread`` preserves exact ordering/semantics while the loop
        stays responsive. The global client lock is still held inside the
        thread (transport safety), but each hold is now a handful of
        requests instead of ~2N.
        """
        from app.db.supabase import (
            async_persistence_slot,
            async_slot_stats_snapshot,
            lock_stats_snapshot,
            persistence_gate_snapshot,
            run_gated_persistence,
        )

        # Free raw payload memory before persistence to prevent memory bloat.
        # This happens BEFORE acquiring the async slot so the slot covers
        # only the synchronous persistence operation (forensics §7).
        for job in normalized_jobs:
            if getattr(job, "raw", None) is not None:
                job.raw = None

        local_cancel = cancel_event or threading.Event()
        lock_before = lock_stats_snapshot()
        async_before = async_slot_stats_snapshot()
        start = time.monotonic()

        thread_box: dict[str, object] = {"name": "", "db_ms": 0}

        def _execute_upsert():
            thread_box["name"] = threading.current_thread().name
            thread_start = time.monotonic()
            try:
                try:
                    return self.job_repository.upsert_jobs(
                        normalized_jobs, source=source, slug=slug, cancel_event=local_cancel
                    )
                except TypeError:
                    return self.job_repository.upsert_jobs(normalized_jobs)
            finally:
                thread_box["db_ms"] = int((time.monotonic() - thread_start) * 1000)

        try:
            async_acquire_start = time.monotonic()
            async with async_persistence_slot(cancel_event=local_cancel, timeout_seconds=timeout_seconds):
                async_wait_ms = int((time.monotonic() - async_acquire_start) * 1000)
                async_hold_start = time.monotonic()
                to_thread_start = time.monotonic()
                # Single-gate: the async slot above is the capacity boundary.
                # run_gated_persistence executes the DB work in the executor
                # thread WITHOUT re-acquiring the sync capacity semaphore.
                result = await asyncio.to_thread(
                    run_gated_persistence,
                    _execute_upsert,
                    cancel_event=local_cancel,
                    timeout_seconds=timeout_seconds,
                )
                to_thread_ms = int((time.monotonic() - to_thread_start) * 1000)
                async_hold_ms = int((time.monotonic() - async_hold_start) * 1000)
        except asyncio.CancelledError:
            local_cancel.set()
            raise
        except Exception:
            local_cancel.set()
            raise

        total_ms = int((time.monotonic() - start) * 1000)
        lock_after = lock_stats_snapshot()
        async_after = async_slot_stats_snapshot()
        gate = persistence_gate_snapshot()
        try:
            platforms = sorted({str(getattr(j, "source_platform", "") or "") for j in normalized_jobs if getattr(j, "source_platform", "")})
            op_source = "+".join(platforms[:3]) or "unknown"
        except Exception:
            op_source = "unknown"
        sync_wait_delta = int(lock_after["wait_ms_total"] - lock_before["wait_ms_total"])
        sync_hold_delta = int(lock_after["hold_ms_total"] - lock_before["hold_ms_total"])
        logger.info(
            "persistence duration_ms=%d phase=upsert op=upsert source=%s discovered=%d "
            "inserted=%d updated=%d unchanged=%d deduplicated=%d skipped=%d "
            "db_requests=%d lock_wait_ms=%d lock_hold_ms=%d lock_waiting=%d "
            "async_wait_ms=%d async_hold_ms=%d async_waiting=%d async_holding=%d "
            "sync_waiting=%d sync_holding=%d to_thread_ms=%d db_thread_ms=%d thread=%s",
            total_ms,
            op_source,
            len(normalized_jobs),
            result.get("inserted", 0),
            result.get("updated", 0),
            result.get("unchanged", 0),
            result.get("deduplicated", 0),
            result.get("skipped", 0),
            getattr(self.job_repository, "last_db_requests", -1),
            sync_wait_delta,
            sync_hold_delta,
            int(lock_after["waiting_now"]),
            async_wait_ms,
            async_hold_ms,
            int(gate.get("async_waiting_now", 0)),
            int(gate.get("async_holding_now", 0)),
            int(gate.get("sync_waiting_now", 0)),
            int(gate.get("sync_holding_now", 0)),
            to_thread_ms,
            int(thread_box.get("db_ms", 0)),
            str(thread_box.get("name", "")),
        )
        # Keep the public ingestion result contract count-only. Operational
        # metrics and insert identity stay on the repository side-channel.
        # Public result stays count-only; operational metrics ride a side-channel
        # so forensics/gating tests can reconcile them without widening the
        # ingestion contract that routes consume.
        self.last_persistence_metrics = {
            "async_wait_ms": async_wait_ms,
            "async_hold_ms": async_hold_ms,
            "to_thread_ms": to_thread_ms,
            "db_thread_ms": int(thread_box.get("db_ms", 0)),
            "persistence_wait_ms": sync_wait_delta,
            "persistence_hold_ms": sync_hold_delta,
            "upsert_ms": total_ms,
            "total_ms": total_ms,
            "path": getattr(self.job_repository, "last_path", "legacy"),
        }
        return result

    async def ingest_ashby_jobs(
        self, slug: str, cancel_event: Optional[threading.Event] = None, source: str = "ashby"
    ) -> dict[str, int]:
        """Ingest jobs from Ashby."""
        adapter = AshbyAdapter(slug)
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [self.job_service.normalize_and_classify(j) for j in crawled_jobs]
        del crawled_jobs
        return await self._persist_offloop(normalized_jobs, source=source, slug=slug, cancel_event=cancel_event)

    async def ingest_greenhouse_jobs(
        self, slug: str, india_only: bool = False, cancel_event: Optional[threading.Event] = None, source: str = "greenhouse"
    ) -> dict[str, int]:
        """Ingest jobs from Greenhouse.

        ``india_only=True`` keeps only India-classified postings (deterministic
        location filter). Default False preserves the full board inventory —
        the canonical global set is never destroyed by ingestion.
        """
        adapter = GreenhouseAdapter(slug, india_only=india_only)
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [self.job_service.normalize_and_classify(j) for j in crawled_jobs]
        del crawled_jobs
        return await self._persist_offloop(normalized_jobs, source=source, slug=slug, cancel_event=cancel_event)

    async def ingest_smartrecruiters_jobs(
        self, slug: str, cancel_event: Optional[threading.Event] = None, source: str = "smartrecruiters"
    ) -> dict[str, int]:
        """Ingest jobs from SmartRecruiters."""
        adapter = SmartRecruitersAdapter(slug)
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [self.job_service.normalize_and_classify(j) for j in crawled_jobs]
        del crawled_jobs
        return await self._persist_offloop(normalized_jobs, source=source, slug=slug, cancel_event=cancel_event)

    async def ingest_lever_jobs(
        self, slug: str, cancel_event: Optional[threading.Event] = None, source: str = "lever"
    ) -> dict[str, int]:
        """Ingest jobs from Lever."""
        adapter = LeverAdapter(slug)
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [self.job_service.normalize_and_classify(j) for j in crawled_jobs]
        del crawled_jobs
        return await self._persist_offloop(normalized_jobs, source=source, slug=slug, cancel_event=cancel_event)

    def _apply_source_quality(self, job: NormalizedJob, careers_url: Optional[str] = None) -> NormalizedJob:
        """Attach verified source provenance to a normalized job.

        The URL (not the retrieval mechanism) decides the source tier; see
        app.crawlers.source_quality.classify_source. Fields are only set on
        objects that actually carry them (NormalizedJob, not CrawledJob).
        """
        provenance = classify_source(
            job.source_platform,
            url=job.apply_url,
            company=job.company,
            careers_url=careers_url,
        )
        model_fields = getattr(type(job), "model_fields", {})

        def _set(name: str, value: Any) -> None:
            if name in model_fields:
                setattr(job, name, value)

        _set("source_tier", provenance.tier)
        _set("source_provider", provenance.provider)
        _set("source_verified", provenance.verified)
        _set("source_confidence", provenance.confidence)
        if careers_url:
            _set("careers_url", careers_url)
        return job

    async def ingest_ycombinator_jobs(
        self, cancel_event: Optional[threading.Event] = None, source: str = "ycombinator", slug: str = "ycombinator"
    ) -> dict[str, int]:
        """Ingest jobs from Y Combinator's Work at a Startup board.

        YC is the discovery layer; each job's apply URL is classified so YC
        postings that point at a company's own domain or ATS board receive a
        better source tier (official > YC board), without duplicating rows.
        """
        from app.crawlers.adapters.ycombinator import YCAdapter

        async with YCAdapter() as adapter:
            crawled_jobs = await adapter.discover_jobs()

        normalized_jobs = [
            self._apply_source_quality(self.job_service.normalize_and_classify(j))
            for j in crawled_jobs
        ]
        del crawled_jobs
        return await self._persist_offloop(normalized_jobs, source=source, slug=slug, cancel_event=cancel_event)

    async def ingest_firecrawl_jobs(
        self,
        careers_url: str,
        company: Optional[str] = None,
        company_website: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        source: str = "firecrawl",
        slug: Optional[str] = None,
    ) -> dict[str, int]:
        """Ingest jobs from a company's official career page via Firecrawl.

        Raises FirecrawlConfigurationError when FIRECRAWL_API_KEY is unset —
        a missing key must never be reported as a successful crawl.
        When the 429 circuit breaker is open, returns a graceful zero-result
        instead of hammering a rate-limited provider (no ARQ retry storm).
        """
        from app.crawlers.adapters.firecrawl import FirecrawlAdapter
        from app.crawlers.firecrawl_client import FirecrawlRateLimitError
        from app.crawlers.generic_fallback import get_firecrawl_breaker

        breaker = get_firecrawl_breaker()
        if breaker.should_skip():
            logger.warning(
                "crawler provider=firecrawl url=%s skipped=true reason=circuit-open",
                careers_url,
            )
            return {"discovered": 0, "inserted": 0, "updated": 0,
                    "unchanged": 0, "deduplicated": 0, "skipped": 0}
        adapter = FirecrawlAdapter(
            careers_url=careers_url,
            company=company,
            company_website=company_website,
        )
        try:
            crawled_jobs = await adapter.discover_jobs()
        except FirecrawlRateLimitError:
            breaker.record_rate_limited()
            raise
        breaker.record_success()
        normalized_jobs = [
            self._apply_source_quality(
                self.job_service.normalize_and_classify(j), careers_url=careers_url
            )
            for j in crawled_jobs
        ]
        del crawled_jobs
        effective_slug = slug or (f"{company}|{careers_url}" if company else careers_url)
        return await self._persist_offloop(normalized_jobs, source=source, slug=effective_slug, cancel_event=cancel_event)

    async def ingest_generic_career_page(
        self,
        careers_url: str,
        company: Optional[str] = None,
        company_website: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        source: str = "firecrawl",
        slug: Optional[str] = None,
    ) -> dict[str, int]:
        """Ingest one generic career page: Crawl4AI primary, Firecrawl fallback.

        Same normalize → source-quality → ``_persist_offloop`` contract as
        every other ``ingest_*`` method — exactly one persistence path.
        """
        from app.crawlers.generic_fallback import crawl_generic_career_page

        crawled_jobs, meta = await crawl_generic_career_page(
            careers_url, company=company, company_website=company_website
        )
        normalized_jobs = [
            self._apply_source_quality(
                self.job_service.normalize_and_classify(j), careers_url=careers_url
            )
            for j in crawled_jobs
        ]
        del crawled_jobs
        effective_slug = slug or (f"{company}|{careers_url}" if company else careers_url)
        result = await self._persist_offloop(normalized_jobs, source=source, slug=effective_slug, cancel_event=cancel_event)
        result = dict(result)
        result["provider"] = meta.get("provider") or "none"
        if meta.get("fallback"):
            result["fallback"] = meta["fallback"]
        return result

    @staticmethod
    def adzuna_rotation_batch(ordinal: int, batch_size: int = ADZUNA_BATCH_SIZE) -> list[str]:
        """Deterministic rotating batch of broad queries for a day-of-year.

        Fixed rotation bug: ``(ordinal * SIZE) % len`` is 0 on every call when
        SIZE == len; ``ordinal % len`` rotates one step per day instead.
        """
        total = len(ADZUNA_BROAD_QUERIES)
        size = max(1, min(int(batch_size), total))
        start = int(ordinal) % total
        return [ADZUNA_BROAD_QUERIES[(start + i) % total] for i in range(size)]

    async def ingest_adzuna_jobs(
        self,
        query: str = "software engineer",
        extra_queries: Optional[list[str]] = None,
        cancel_event: Optional[threading.Event] = None,
        source: str = "adzuna",
        slug: Optional[str] = None,
    ) -> dict[str, int]:
        """Ingest jobs from Adzuna, India-first.

        Adzuna's API is country-scoped via the URL path
        (``/v1/api/jobs/in/search/{page}`` for India). We run a primary
        search against India ("in") so real India-based roles appear, plus a
        secondary remote/global search so global/remote roles are still
        present — India-first, not India-only.

        ``extra_queries`` lets us broaden coverage for companies that don't
        expose a direct ATS board (e.g. banks, large enterprises on Workday).
        """
        from app.config import get_settings

        settings = get_settings()
        per_page = getattr(settings, "adzuna_results_per_page", 50)
        batch_size = getattr(settings, "adzuna_queries_per_crawl", ADZUNA_BATCH_SIZE)
        adapter = AdzunaAdapter()
        crawled_jobs: list = []

        # Primary: India-scoped search + secondary remote/global so non-India
        # remote work still shows (India-first, not India-only).
        india_jobs = await adapter.search_by_query(query, country="in", results_per_page=per_page)
        crawled_jobs.extend(india_jobs)
        remote_jobs = await adapter.search_by_query("remote", country="gb", results_per_page=per_page)
        crawled_jobs.extend(remote_jobs)
        global_jobs = await adapter.search_by_query(query, country="us", results_per_page=per_page)
        crawled_jobs.extend(global_jobs)

        # Tertiary: deterministic broad-query rotation (bounded budget).
        # One batch of `batch_size` India-scoped queries per run; the batch
        # rotates by day-of-year so every query is exercised over time.
        # ponytail: 3 queries x 1 country = 3 calls/crawl (~180/mo), not the
        # full matrix.
        ordinal = datetime.now(timezone.utc).timetuple().tm_yday
        for broad_query in self.adzuna_rotation_batch(ordinal, batch_size):
            for country in ADZUNA_BROAD_COUNTRIES:
                crawled_jobs.extend(
                    await adapter.search_by_query(broad_query, country=country, results_per_page=per_page)
                )

        # Company-inclusive extras for enterprises without direct ATS boards.
        for extra in extra_queries or []:
            crawled_jobs.extend(await adapter.search_by_query(extra, country="in", results_per_page=per_page))
            crawled_jobs.extend(await adapter.search_by_query(extra, country="us", results_per_page=per_page))

        normalized_jobs = [self.job_service.normalize_and_classify(j) for j in crawled_jobs]
        del crawled_jobs
        effective_slug = slug or query
        return await self._persist_offloop(self._drop_invalid(normalized_jobs), source=source, slug=effective_slug, cancel_event=cancel_event)

    @staticmethod
    def _drop_invalid(jobs: list) -> list:
        """Filter INVALID jobs; warnings/stale pass through to the lifecycle."""
        from app.services.jobs.job_service import validate_job

        kept = []
        for job in jobs:
            try:
                status, _ = validate_job(job)
            except Exception:
                continue
            if status == "INVALID":
                continue
            kept.append(job)
        return kept

    async def ingest_jobspy_jobs(
        self,
        query: str = "data analyst India",
        location: str = "India",
        results_wanted: Optional[int] = None,
        hours_old: Optional[int] = None,
        site_names: Optional[list[str]] = None,
        cancel_event: Optional[threading.Event] = None,
        source: str = "jobspy",
        slug: Optional[str] = None,
    ) -> dict[str, int]:
        """Ingest one JobSpy query into the canonical pipeline.

        Single-search path (unchanged contract: returns the upsert counters
        verbatim). The production scheduler uses ``ingest_jobspy_scheduled``
        for the bounded rotation batch instead.
        """
        from app.config import get_settings
        from app.crawlers.adapters.jobspy import JobSpyAdapter

        settings = get_settings()
        if not getattr(settings, "jobspy_enabled", True):
            return {"discovered": 0, "inserted": 0, "updated": 0,
                    "unchanged": 0, "deduplicated": 0, "skipped": 0}
        adapter = JobSpyAdapter(
            query=query,
            location=location,
            results_wanted=results_wanted or getattr(settings, "jobspy_results_wanted", 50),
            timeout_seconds=getattr(settings, "jobspy_timeout_seconds", 60.0),
            hours_old=hours_old,
            site_names=site_names,
        )
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [
            self._apply_source_quality(self.job_service.normalize_and_classify(j))
            for j in crawled_jobs
        ]
        del crawled_jobs
        effective_slug = slug or query
        return await self._persist_offloop(self._drop_invalid(normalized_jobs), source=source, slug=effective_slug, cancel_event=cancel_event)

    @staticmethod
    def jobspy_rotation_batch(
        ordinal: int,
        query_batch_size: Optional[int] = None,
        location_batch_size: Optional[int] = None,
    ):
        """Deterministic bounded JobSpy search batch for one crawl cycle.

        Resolves settings-backed defaults (JOBSPY_QUERY_BATCH_SIZE /
        JOBSPY_LOCATION_BATCH_SIZE / JOBSPY_SITES / JOBSPY_FRESHNESS_BUCKETS)
        and delegates to the pure strategy rotation. See
        ``app.services.jobs.jobspy_strategy.rotation_batch``.
        """
        from app.config import get_settings
        from app.services.jobs.jobspy_strategy import (
            parse_freshness_buckets,
            parse_sites,
            rotation_batch,
        )

        settings = get_settings()
        batch_size = (
            query_batch_size
            if query_batch_size is not None
            else int(getattr(settings, "jobspy_query_batch_size", 4))
        )
        loc_size = (
            location_batch_size
            if location_batch_size is not None
            else int(getattr(settings, "jobspy_location_batch_size", 2))
        )
        return rotation_batch(
            ordinal,
            query_batch_size=batch_size,
            location_batch_size=loc_size,
            sites=parse_sites(getattr(settings, "jobspy_sites", "")),
            results_wanted=int(getattr(settings, "jobspy_results_wanted", 50)),
            freshness_buckets=parse_freshness_buckets(
                getattr(settings, "jobspy_freshness_buckets", "")
            ),
        )

    async def ingest_jobspy_scheduled(
        self,
        extra_query: Optional[str] = None,
        ordinal: Optional[int] = None,
        throttle=None,
        breaker=None,
        cache=None,
        fetch_fn=None,
        cancel_event: Optional[threading.Event] = None,
        source: str = "jobspy",
        slug: Optional[str] = None,
    ) -> dict:
        """Run one bounded JobSpy discovery batch (the production path).

        Executes the deterministic rotation batch sequentially-bounded
        (``JOBSPY_MAX_CONCURRENT`` semaphore + per-provider locks so the
        same provider's searches stay spaced by its minimum delay),
        normalizes through the canonical pipeline, and persists once via
        the existing off-loop boundary.

        Reliability: one provider/search failure never aborts the others;
        429s back off without retry; repeated failures open the provider
        circuit; identical searches are skipped inside the freshness
        window. Deduplication reuses the canonical pipeline verbatim —
        ATS rows stay authoritative (a JobSpy re-discovery of an ATS URL
        keeps its own ``(source_platform, external_job_id)`` identity and
        can never overwrite the official row).
        """
        from app.config import get_settings
        from app.crawlers.adapters.jobspy import JobSpyAdapter
        from app.services.jobs.jobspy_strategy import (
            JobSpySearch,
            ats_covered_companies,
            parse_freshness_buckets,
            parse_sites,
            score_companies_from_jobs,
        )
        from app.services.jobs.jobspy_throttle import (
            ProviderOutcomeRecord,
            SearchCache,
            get_jobspy_breaker,
            get_jobspy_cache,
            get_jobspy_throttle,
            is_rate_limit_error,
        )

        settings = get_settings()
        base_zeros: dict = {
            "discovered": 0, "inserted": 0, "updated": 0, "unchanged": 0,
            "deduplicated": 0, "skipped": 0, "valid": 0, "rejected": 0,
            "incremental": 0, "fresher": 0, "internships": 0, "walkins": 0,
            "emerging_company_jobs": 0, "unique_companies": 0,
            "searches_executed": 0, "searches_skipped": 0,
            "provider_outcomes": [],
        }
        if not getattr(settings, "jobspy_enabled", True):
            logger.info("jobspy run completed enabled=false incremental=0")
            return dict(base_zeros)

        sites = parse_sites(getattr(settings, "jobspy_sites", ""))
        buckets = parse_freshness_buckets(
            getattr(settings, "jobspy_freshness_buckets", "")
        )
        if ordinal is None:
            ordinal = datetime.now(timezone.utc).timetuple().tm_yday
        batch = self.jobspy_rotation_batch(ordinal)
        if extra_query and str(extra_query).strip():
            first_site = (sites or ["indeed"])[0]
            bucket = buckets[int(ordinal) % len(buckets)]
            from app.services.jobs.jobspy_strategy import HOURS_OLD_SUPPORTED_SITES

            batch = list(batch) + [
                JobSpySearch(
                    query=str(extra_query).strip(),
                    location="India",
                    site=first_site,
                    hours_old=bucket if first_site in HOURS_OLD_SUPPORTED_SITES else None,
                    results_wanted=int(getattr(settings, "jobspy_results_wanted", 50)),
                    query_family="ad_hoc",
                )
            ]
        from app.services.jobs.jobspy_strategy import MAX_JOBSPY_SEARCHES_PER_RUN

        batch = list(batch)[: MAX_JOBSPY_SEARCHES_PER_RUN + 1]

        throttle = throttle or get_jobspy_throttle()
        breaker = breaker or get_jobspy_breaker()
        cache = cache or get_jobspy_cache()
        timeout_seconds = float(getattr(settings, "jobspy_timeout_seconds", 60.0))
        max_concurrent = max(1, min(int(getattr(settings, "jobspy_max_concurrent", 2)), 3))

        logger.info(
            "jobspy run started searches=%d sites=%s buckets=%s ordinal=%d",
            len(batch), ",".join(sites), ",".join(str(b) for b in buckets), int(ordinal),
        )
        if not batch:
            logger.info("jobspy run completed incremental=0 reason=no-searches")
            return dict(base_zeros)

        semaphore = asyncio.Semaphore(max_concurrent)
        provider_locks: dict[str, asyncio.Lock] = {}

        def _lock_for(site: str) -> asyncio.Lock:
            key = str(site or "").lower()
            lock = provider_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                provider_locks[key] = lock
            return lock

        async def _run_search(search: JobSpySearch):
            record = ProviderOutcomeRecord(
                provider=search.site,
                query_family=search.query_family,
                location=search.location,
                requested=search.results_wanted,
            )
            key = SearchCache.key(search.site, search.query, search.location, search.hours_old)
            if cache.is_fresh(key):
                record.outcome = "skipped_cached"
                logger.info(
                    "jobspy provider=%s query_family=%s skipped=true reason=freshness-cache",
                    search.site, search.query_family,
                )
                return [], record
            if breaker.should_skip(search.site):
                record.outcome = "skipped_circuit"
                logger.info(
                    "jobspy circuit_open=true provider=%s query_family=%s",
                    search.site, search.query_family,
                )
                return [], record
            start = time.monotonic()
            normalized: list = []
            try:
                async with semaphore:
                    async with _lock_for(search.site):
                        await throttle.wait(search.site)
                        adapter = JobSpyAdapter(
                            query=search.query,
                            location=search.location,
                            results_wanted=search.results_wanted,
                            site_names=[search.site],
                            timeout_seconds=timeout_seconds,
                            fetch_fn=fetch_fn,
                            hours_old=search.hours_old,
                        )
                        crawled = await adapter.discover_jobs()
                        throttle.record(search.site)
                        error = adapter.last_error
                        outcome = adapter.last_outcome
                        if error is not None and is_rate_limit_error(error):
                            breaker.record_rate_limited(search.site)
                            record.outcome = "rate_limited"
                            record.rate_limited = True
                            logger.info(
                                "jobspy rate_limited=true provider=%s query_family=%s",
                                search.site, search.query_family,
                            )
                        elif error is not None or outcome == "transient":
                            breaker.record_failure(search.site)
                            record.outcome = "transient"
                        elif outcome == "config":
                            record.outcome = "config"
                            logger.info(
                                "jobspy provider=%s query_family=%s outcome=config "
                                "reason=missing-dependency",
                                search.site, search.query_family,
                            )
                        else:
                            breaker.record_success(search.site)
                            cache.mark(key)
                        record.discovered = len(crawled) if isinstance(crawled, list) else 0
                        for crawled_job in crawled or []:
                            try:
                                normalized_job = self._apply_source_quality(
                                    self.job_service.normalize_and_classify(crawled_job)
                                )
                            except Exception as exc:
                                logger.warning("jobspy record skipped: %s", exc)
                                continue
                            normalized.append(normalized_job)
                        kept = self._drop_invalid(normalized)
                        record.valid = len(kept)
                        normalized = kept
            except Exception as exc:
                # Isolation: a search-level failure (throttle/сache bugs,
                # coding errors) never aborts the sibling searches.
                logger.warning(
                    "jobspy provider=%s query_family=%s failed isolated: %s",
                    search.site, search.query_family, exc,
                )
                try:
                    breaker.record_failure(search.site)
                except Exception:
                    pass
                record.outcome = "transient"
                normalized = []
            record.elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "jobspy provider=%s query_family=%s location=%s "
                "discovered=%d valid=%d elapsed_ms=%d outcome=%s",
                record.provider, record.query_family, record.location,
                record.discovered, record.valid, record.elapsed_ms, record.outcome,
            )
            return normalized, record

        results = await asyncio.gather(*(_run_search(search) for search in batch))
        all_normalized: list = []
        outcome_dicts: list[dict] = []
        executed = 0
        skipped = 0
        for normalized, record in results:
            all_normalized.extend(normalized)
            outcome_dicts.append(record.__dict__)
            if record.outcome in ("skipped_cached", "skipped_circuit"):
                skipped += 1
            else:
                executed += 1

        effective_slug = slug or extra_query or "jobspy_scheduled"
        persist_result = await self._persist_offloop(all_normalized, source=source, slug=effective_slug, cancel_event=cancel_event)
        result: dict = dict(persist_result)
        result["discovered"] = sum(r["discovered"] for r in outcome_dicts)
        result["valid"] = len(all_normalized)
        result["rejected"] = max(result["discovered"] - result["valid"], 0)
        result["incremental"] = int(result.get("inserted", 0))

        fresher = sum(
            1 for job in all_normalized
            if str(getattr(job, "experience_level", "") or "").lower() in ("entry", "intern")
        )
        internships = sum(
            1 for job in all_normalized
            if str(getattr(job, "experience_level", "") or "").lower() == "intern"
        )
        walkins = sum(
            1 for job in all_normalized
            if bool((getattr(job, "mass_hiring_details", None) or {}).get("walkin_detected"))
        )
        try:
            scored = score_companies_from_jobs(all_normalized, ats_covered_companies())
        except Exception as exc:
            logger.warning("jobspy startup_signal scoring failed (isolated): %s", exc)
            scored = []
        emerging_labels = {"emerging hiring company", "under-covered company"}
        emerging_jobs = sum(
            int(item.get("stats", {}).get("active_openings", 0))
            for item in scored
            if item.get("label") in emerging_labels
        )
        result["fresher"] = fresher
        result["internships"] = internships
        result["walkins"] = walkins
        result["emerging_company_jobs"] = emerging_jobs
        result["unique_companies"] = len(scored)
        result["searches_executed"] = executed
        result["searches_skipped"] = skipped
        result["provider_outcomes"] = outcome_dicts

        logger.info(
            "jobspy discovered=%d incremental=%d fresher=%d walkin=%d "
            "startup_signal=%d unique_companies=%d",
            result["discovered"], result["incremental"], fresher, walkins,
            emerging_jobs, len(scored),
        )
        for item in scored[:10]:
            if item.get("label") in emerging_labels:
                logger.info(
                    "jobspy startup_signal=%s company=%s score=%d reasons=%s",
                    item["label"], item["company"], item["score"],
                    ",".join(item.get("reasons", [])[:4]),
                )
        logger.info(
            "jobspy run completed incremental=%d executed=%d skipped=%d",
            result["incremental"], executed, skipped,
        )
        return result

    async def ingest_all(self) -> dict[str, dict[str, int]]:
        """Ingest jobs from all configured sources.

        Each source is isolated so a failure in one does not prevent the
        others from completing. Partial failures are reported per-source.
        """
        results: dict[str, dict[str, int]] = {}

        # Ashby
        try:
            results["ashby"] = await self.ingest_ashby_jobs("notion")
        except Exception as e:
            results["ashby"] = {"error": str(e)}

        # Greenhouse
        try:
            results["greenhouse"] = await self.ingest_greenhouse_jobs("stripe", india_only=True)
        except Exception as e:
            results["greenhouse"] = {"error": str(e)}

        # SmartRecruiters
        try:
            results["smartrecruiters"] = await self.ingest_smartrecruiters_jobs("servicenow")
        except Exception as e:
            results["smartrecruiters"] = {"error": str(e)}

        # Lever
        try:
            results["lever"] = await self.ingest_lever_jobs("coupa")
        except Exception as e:
            results["lever"] = {"error": str(e)}

        # Adzuna
        try:
            adzuna_extra = [
                # Software Engineering
                "software engineer Accenture",
                "software engineer Barclays",
                "software engineer HSBC",
                "software engineer JPMorgan",
                "software engineer Morgan Stanley",
                "software engineer Citi",
                "software engineer Visa",
                "software engineer Mastercard",
                "software engineer BNY",
                "software engineer IBM",
                "software engineer Atlassian",
                "software engineer India",
                "software engineer Bangalore",
                # Data & Analytics
                "data analyst India",
                "data analyst Bangalore",
                "data analyst Hyderabad",
                "data analyst Pune",
                "data analyst Chennai",
                "data analyst Mumbai",
                "business analyst India",
                "business intelligence analyst India",
                "bi analyst India",
                "data scientist India",
                "data engineer India",
                "machine learning engineer India",
                # Product & Business
                "product manager India",
                "project manager India",
                "program manager India",
                # Finance & BFSI
                "financial analyst India",
                "accountant India",
                "auditor India",
                # Sales & Marketing
                "sales executive India",
                "marketing executive India",
                # HR & People
                "recruiter India",
                "hr executive India",
                # Design & Creative
                "ui designer India",
                "ux designer India",
                "graphic designer India",
                # Customer & Operations
                "customer support India",
                "operations executive India",
                # Supply Chain & Logistics
                "supply chain analyst India",
                "procurement analyst India",
                # Engineering (Core)
                "civil engineer India",
                "mechanical engineer India",
                "electrical engineer India",
                "electronics engineer India",
            ]
            results["adzuna"] = await self.ingest_adzuna_jobs(extra_queries=adzuna_extra)
        except Exception as e:
            results["adzuna"] = {"error": str(e)}

        # SmartRecruiters (Visa confirmed to have live postings)
        try:
            results["smartrecruiters_visa"] = await self.ingest_smartrecruiters_jobs("visa")
        except Exception as e:
            results["smartrecruiters_visa"] = {"error": str(e)}

        return results

    async def ingest_instahyre_jobs(
        self,
        query: str = "software engineer",
        location: str = "India",
        cancel_event: Optional[threading.Event] = None,
        source: str = "instahyre",
        slug: Optional[str] = None,
    ) -> dict[str, int]:
        """Ingest jobs from Instahyre India adapter."""
        from app.crawlers.adapters.instahyre import InstahyreAdapter

        adapter = InstahyreAdapter(query=query, location=location)
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [
            self._apply_source_quality(self.job_service.normalize_and_classify(j))
            for j in crawled_jobs
        ]
        del crawled_jobs
        effective_slug = slug or query
        return await self._persist_offloop(
            self._drop_invalid(normalized_jobs),
            source=source,
            slug=effective_slug,
            cancel_event=cancel_event,
        )

    async def ingest_hirist_jobs(
        self,
        query: str = "software engineer",
        location: str = "India",
        cancel_event: Optional[threading.Event] = None,
        source: str = "hirist",
        slug: Optional[str] = None,
    ) -> dict[str, int]:
        """Ingest jobs from Hirist India adapter."""
        from app.crawlers.adapters.hirist import HiristAdapter

        adapter = HiristAdapter(query=query, location=location)
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [
            self._apply_source_quality(self.job_service.normalize_and_classify(j))
            for j in crawled_jobs
        ]
        del crawled_jobs
        effective_slug = slug or query
        return await self._persist_offloop(
            self._drop_invalid(normalized_jobs),
            source=source,
            slug=effective_slug,
            cancel_event=cancel_event,
        )

    async def ingest_naukri_jobs(
        self,
        query: str = "software-engineer",
        location: str = "india",
        cancel_event: Optional[threading.Event] = None,
        source: str = "naukri",
        slug: Optional[str] = None,
    ) -> dict[str, int]:
        """Ingest jobs from Naukri India adapter (Firecrawl/Playwright)."""
        from app.crawlers.adapters.naukri import NaukriAdapter

        adapter = NaukriAdapter(query=query, location=location)
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [
            self._apply_source_quality(self.job_service.normalize_and_classify(j))
            for j in crawled_jobs
        ]
        del crawled_jobs
        effective_slug = slug or query
        return await self._persist_offloop(
            self._drop_invalid(normalized_jobs),
            source=source,
            slug=effective_slug,
            cancel_event=cancel_event,
        )



