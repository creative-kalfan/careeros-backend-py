"""Job ingestion service: orchestrates the full job ingestion pipeline."""

from __future__ import annotations

from typing import Optional

from app.crawlers.adapters.ashby import AshbyAdapter
from app.crawlers.adapters.greenhouse import GreenhouseAdapter
from app.crawlers.adapters.lever import LeverAdapter
from app.crawlers.adapters.smartrecruiters import SmartRecruitersAdapter
from app.crawlers.aggregators.adzuna import AdzunaAdapter
from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository
from app.services.jobs.job_service import JobService


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

        # Primary: India-scoped search.
        india_jobs = await adapter.search_by_query(query, country="in")
        crawled_jobs.extend(india_jobs)

        # Secondary: remote/global roles so non-India remote work still shows.
        remote_jobs = await adapter.search_by_query("remote", country="gb")
        crawled_jobs.extend(remote_jobs)
        global_jobs = await adapter.search_by_query(query, country="us")
        crawled_jobs.extend(global_jobs)

        # Tertiary: company-inclusive queries for enterprises without direct
        # ATS adapters (Workday/custom portals). Adzuna aggregates listings
        # regardless of the company's internal ATS.
        for extra in extra_queries or []:
            company_jobs_in = await adapter.search_by_query(extra, country="in")
            crawled_jobs.extend(company_jobs_in)
            company_jobs_us = await adapter.search_by_query(extra, country="us")
            crawled_jobs.extend(company_jobs_us)

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