"""Source escalation + Firecrawl ingestion tests.

Covers the CRITICAL requirement: when Firecrawl later discovers an existing
job on the company's OFFICIAL career page, the canonical row is upgraded in
place — never duplicated — and the official provenance is recorded.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.crawlers.models import CrawledJob
from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository
from app.services.jobs.job_ingestion_service import JobIngestionService
from app.services.jobs.source_priority import source_quality_bonus


def _crawled(url: str, source: str = "firecrawl") -> CrawledJob:
    return CrawledJob(
        title="Backend Engineer",
        company="Acme",
        description="Build things",
        apply_url=url,
        external_job_id="ext-1" if source != "firecrawl" else None,
        source_platform=source,
    )


def _normalized(tier: int, source: str = "adzuna", url: str = "https://indeed.com/x") -> NormalizedJob:
    return NormalizedJob(
        title="Backend Engineer",
        company="Acme",
        external_job_id="ext-1",
        source_platform=source,
        apply_url=url,
        source_tier=tier,
        source_verified=tier in (1, 2, 3),
    )


class TestSourceEscalation:
    def _repo(self) -> tuple[JobRepository, MagicMock]:
        client = MagicMock()
        client.table.return_value = client
        for m in ("select", "eq", "update", "insert", "limit"):
            setattr(client, m, MagicMock(return_value=client))
        client.execute.return_value = MagicMock(data=[], count=0)
        repo = JobRepository(client)
        repo._has_last_seen_at = False
        repo._has_provenance = True
        return repo, client

    def test_official_upgrade_updates_existing_row_not_duplicate(self):
        repo, client = self._repo()
        existing = {
            "id": "job-1",
            "title": "Backend Engineer",
            "company": "Acme",
            "external_job_id": "ext-1",
            "source_platform": "adzuna",
            "source_tier": 5,
            "source_provider": "adzuna",
        }
        with patch.object(JobRepository, "_find_by_identity", return_value=existing):
            result = repo.upsert_jobs([_normalized(1, "firecrawl", "https://acme.com/jobs/1")])

        assert result["updated"] == 1
        assert result["inserted"] == 0
        # Update carries the upgraded provenance + history.
        row = client.update.call_args.args[0]
        assert row["source_tier"] == 1
        assert row["source_provider"] == "firecrawl"
        assert row["source_verified"] is True
        assert row["source_history"][-1]["source_tier"] == 5
        client.insert.assert_not_called()

    def test_worse_source_never_downgrades_existing(self):
        repo, client = self._repo()
        existing = {
            "id": "job-1",
            "title": "Different Title",
            "company": "Acme",
            "external_job_id": "ext-1",
            "source_platform": "firecrawl",
            "source_tier": 1,
            "source_provider": "firecrawl",
        }
        with patch.object(JobRepository, "_find_by_identity", return_value=existing):
            repo.upsert_jobs([_normalized(5, "adzuna")])
        row = client.update.call_args.args[0]
        assert row["source_tier"] == 1  # kept the better tier
        assert row["source_provider"] == "firecrawl"

    def test_tier_bonus_positive_for_official_only(self):
        assert source_quality_bonus({"source_tier": 1}) > 0
        assert source_quality_bonus({"source_tier": 5}) < 0
        assert source_quality_bonus({}) == 0
        assert source_quality_bonus(None) == 0


class TestFirecrawlIngestion:
    @pytest.mark.asyncio
    async def test_ingest_firecrawl_jobs_attaches_provenance(self):
        service = JobIngestionService()
        service.job_repository = MagicMock()
        service.job_repository.upsert_jobs.return_value = {"discovered": 1, "inserted": 1}
        service.job_service = MagicMock()
        service.job_service.normalize_and_classify.side_effect = lambda c: NormalizedJob(
            title=c.title,
            company=c.company,
            description=c.description,
            apply_url=c.apply_url,
            source_platform=c.source_platform,
            external_job_id="fc-1",
        )

        fake_adapter = MagicMock()
        fake_adapter.discover_jobs = AsyncMock(
            return_value=[_crawled("https://acme.com/jobs/1")]
        )

        with patch(
            "app.crawlers.adapters.firecrawl.FirecrawlAdapter", return_value=fake_adapter
        ) as adapter_cls:
            result = await service.ingest_firecrawl_jobs(
                careers_url="https://acme.com/careers", company="Acme"
            )

        adapter_cls.assert_called_once_with(
            careers_url="https://acme.com/careers",
            company="Acme",
            company_website=None,
        )
        assert result == {"discovered": 1, "inserted": 1}
        upserted = service.job_repository.upsert_jobs.call_args.args[0]
        job = upserted[0]
        assert job.source_tier == 1  # official company domain
        assert job.source_verified is True
        assert job.careers_url == "https://acme.com/careers"

    @pytest.mark.asyncio
    async def test_ingest_firecrawl_jobs_unverified_domain_is_secondary(self):
        service = JobIngestionService()
        service.job_repository = MagicMock()
        service.job_repository.upsert_jobs.return_value = {"discovered": 1}
        service.job_service = MagicMock()
        service.job_service.normalize_and_classify.side_effect = lambda c: NormalizedJob(
            title=c.title,
            company=c.company,
            apply_url=c.apply_url,
            source_platform=c.source_platform,
            external_job_id="fc-2",
        )

        fake_adapter = MagicMock()
        fake_adapter.discover_jobs = AsyncMock(
            return_value=[_crawled("https://randomjobs.net/jobs/9")]
        )
        with patch(
            "app.crawlers.adapters.firecrawl.FirecrawlAdapter", return_value=fake_adapter
        ):
            await service.ingest_firecrawl_jobs(
                careers_url="https://portal.example.com/careers", company="Acme"
            )
        job = service.job_repository.upsert_jobs.call_args.args[0][0]
        assert job.source_tier == 4  # NOT official despite Firecrawl retrieval
        assert job.source_verified is False


class TestWorkerFirecrawlBranch:
    @pytest.mark.asyncio
    async def test_crawl_company_job_firecrawl_branch(self):
        from app.workers.jobs import crawl_jobs
        from app.workers.jobs.crawl_jobs import crawl_company_job

        ingestion = MagicMock()
        ingestion.ingest_firecrawl_jobs = AsyncMock(return_value={"discovered": 2, "inserted": 2})
        ingestion.job_repository.deactivate_stale_jobs.return_value = 0

        class FakeBus:
            async def publish(self, event, context=None):
                class R:
                    succeeded = True
                    failures = []
                return R()

        with patch.object(crawl_jobs, "JobIngestionService", return_value=ingestion), \
             patch("app.events.get_event_bus", return_value=FakeBus()):
            result = await crawl_company_job(
                {"job_id": "t"}, "firecrawl", "Acme|https://acme.com/careers"
            )

        assert result["success"] is True
        ingestion.ingest_firecrawl_jobs.assert_awaited_once_with(
            careers_url="https://acme.com/careers", company="Acme"
        )

    @pytest.mark.asyncio
    async def test_crawl_company_job_firecrawl_requires_careers_url(self):
        from app.workers.jobs.crawl_jobs import crawl_company_job

        with pytest.raises(ValueError):
            await crawl_company_job({"job_id": "t"}, "firecrawl", "Acme")


