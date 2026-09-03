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
# rotating by date so coverage is deterministic and restart-safe.
ADZUNA_BROAD_QUERIES = [
    "software engineer India",
    "data engineer India",
    "backend developer India",
    "full stack developer India",
    "machine learning engineer India",
    "product manager India",
    "data analyst India",
    "devops engineer India",
]
ADZUNA_BATCH_SIZE = 8


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

    async def ingest_greenhouse_jobs(self, slug: str) -> dict[str, int]:
        """Ingest jobs from Greenhouse."""
        adapter = GreenhouseAdapter(slug)
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

    async def ingest_adzuna_jobs(self, query: str = "software engineer", extra_queries: Optional[list[str]] = None) -> dict[str, int]:
        """Ingest jobs from Adzuna, India-first.

        Adzuna's API is country-scoped via the URL path. We run a primary
        search against India ("in") so real India-based roles appear, plus a
        secondary remote/global search ("remote" keyword across gb/us) so
        global/remote roles are still present — India-first, not India-only.

        ``extra_queries`` lets us broaden coverage for companies that don't
        expose a direct ATS board (e.g. banks, large enterprises on Workday).
        """
        adapter = AdzunaAdapter()
        crawled_jobs: list = []

        # Primary: India-scoped search + secondary remote/global so non-India
        # remote work still shows (India-first, not India-only).
        india_jobs = await adapter.search_by_query(query, country="in")
        crawled_jobs.extend(india_jobs)
        remote_jobs = await adapter.search_by_query("remote", country="gb")
        crawled_jobs.extend(remote_jobs)
        global_jobs = await adapter.search_by_query(query, country="us")
        crawled_jobs.extend(global_jobs)

        # Tertiary: deterministic broad-query rotation (bounded budget).
        # One batch of ADZUNA_BATCH_SIZE broad queries × 3 countries per run;
        # the batch rotates by date so every query is exercised over time.
        ordinal = datetime.utcnow().timetuple().tm_yday
        batch_start = (ordinal * ADZUNA_BATCH_SIZE) % len(ADZUNA_BROAD_QUERIES)
        batch = [
            ADZUNA_BROAD_QUERIES[(batch_start + i) % len(ADZUNA_BROAD_QUERIES)]
            for i in range(ADZUNA_BATCH_SIZE)
        ]
        for broad_query in batch:
            for country in ("in", "gb", "us"):
                crawled_jobs.extend(await adapter.search_by_query(broad_query, country=country))

        # Company-inclusive extras for enterprises without direct ATS boards.
        for extra in extra_queries or []:
            crawled_jobs.extend(await adapter.search_by_query(extra, country="in"))
            crawled_jobs.extend(await adapter.search_by_query(extra, country="us"))

        normalized_jobs = [self.job_service.normalize_and_classify(j) for j in crawled_jobs]
        return self.job_repository.upsert_jobs(normalized_jobs)

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