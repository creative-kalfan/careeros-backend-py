"""Job ingestion service: orchestrates the full job ingestion pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

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
    # Data analytics & BI (task priority)
    "data analyst India",
    "data analytics India",
    "business intelligence India",
    "BI analyst India",
    "business analyst India",
    "reporting analyst India",
    "risk analyst India",
    "risk analytics India",
    "financial analyst India",
    # Data engineering
    "data engineer India",
    "data engineering India",
    "analytics engineer India",
    "ETL developer India",
    "data warehouse India",
    # AI / ML
    "machine learning India",
    "AI engineer India",
    "artificial intelligence India",
    "data scientist India",
    "generative AI India",
    # Backend / software engineering
    "backend engineer India",
    "software engineer India",
    "Python backend India",
    "Java backend India",
    "API developer India",
    # SAP
    "SAP India",
    "SAP ABAP India",
    "ABAP developer India",
    "SAP HANA India",
    # City-scoped (measured incremental India coverage, task §7)
    "data analyst Hyderabad",
    "data analyst Pune",
    "data analyst Mumbai",
    "data analyst Chennai",
    "data analyst Bengaluru",
    "data analyst Gurugram",
    "data engineer Bengaluru",
    "software engineer Bengaluru",
    "software engineer Hyderabad",
    "software engineer Pune",
    "software engineer Chennai",
]
ADZUNA_BATCH_SIZE = 3
# Broad rotation is India-scoped only; the primary query already covers
# remote/global. Keeps the free-tier budget bounded (primary 3 + batch 3 =
# ~6 calls/crawl/day, ~180/mo, well inside the ~1000/mo free allowance).
ADZUNA_BROAD_COUNTRIES = ("in",)


class JobIngestionService:
    """Orchestrates the job ingestion pipeline."""

    def __init__(
        self,
        job_repository: Optional[JobRepository] = None,
        job_service: Optional[JobService] = None,
    ) -> None:
        self.job_repository = job_repository or JobRepository()
        self.job_service = job_service or JobService()

    async def ingest_ashby_jobs(self, slug: str) -> dict[str, int]:
        """Ingest jobs from Ashby."""
        adapter = AshbyAdapter(slug)
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [self.job_service.normalize_and_classify(j) for j in crawled_jobs]
        return self.job_repository.upsert_jobs(normalized_jobs)

    async def ingest_greenhouse_jobs(self, slug: str, india_only: bool = False) -> dict[str, int]:
        """Ingest jobs from Greenhouse.

        ``india_only=True`` keeps only India-classified postings (deterministic
        location filter). Default False preserves the full board inventory —
        the canonical global set is never destroyed by ingestion.
        """
        adapter = GreenhouseAdapter(slug, india_only=india_only)
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [self.job_service.normalize_and_classify(j) for j in crawled_jobs]
        return self.job_repository.upsert_jobs(normalized_jobs)

    async def ingest_smartrecruiters_jobs(self, slug: str) -> dict[str, int]:
        """Ingest jobs from SmartRecruiters."""
        adapter = SmartRecruitersAdapter(slug)
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [self.job_service.normalize_and_classify(j) for j in crawled_jobs]
        return self.job_repository.upsert_jobs(normalized_jobs)

    async def ingest_lever_jobs(self, slug: str) -> dict[str, int]:
        """Ingest jobs from Lever."""
        adapter = LeverAdapter(slug)
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [self.job_service.normalize_and_classify(j) for j in crawled_jobs]
        return self.job_repository.upsert_jobs(normalized_jobs)

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

    async def ingest_ycombinator_jobs(self) -> dict[str, int]:
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
        return self.job_repository.upsert_jobs(normalized_jobs)

    async def ingest_firecrawl_jobs(
        self,
        careers_url: str,
        company: Optional[str] = None,
        company_website: Optional[str] = None,
    ) -> dict[str, int]:
        """Ingest jobs from a company's official career page via Firecrawl.

        Raises FirecrawlConfigurationError when FIRECRAWL_API_KEY is unset —
        a missing key must never be reported as a successful crawl.
        """
        from app.crawlers.adapters.firecrawl import FirecrawlAdapter

        adapter = FirecrawlAdapter(
            careers_url=careers_url,
            company=company,
            company_website=company_website,
        )
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [
            self._apply_source_quality(
                self.job_service.normalize_and_classify(j), careers_url=careers_url
            )
            for j in crawled_jobs
        ]
        return self.job_repository.upsert_jobs(normalized_jobs)

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

    async def ingest_adzuna_jobs(self, query: str = "software engineer", extra_queries: Optional[list[str]] = None) -> dict[str, int]:
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
        return self.job_repository.upsert_jobs(self._drop_invalid(normalized_jobs))

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
    ) -> dict[str, int]:
        """Ingest Naukri/LinkedIn coverage via JobSpy into the canonical pipeline."""
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
        )
        crawled_jobs = await adapter.discover_jobs()
        normalized_jobs = [
            self._apply_source_quality(self.job_service.normalize_and_classify(j))
            for j in crawled_jobs
        ]
        return self.job_repository.upsert_jobs(self._drop_invalid(normalized_jobs))

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
            results["greenhouse"] = await self.ingest_greenhouse_jobs("stripe")
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