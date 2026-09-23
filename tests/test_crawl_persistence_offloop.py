"""Sync Supabase persistence must run off the ARQ event-loop thread."""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.crawlers.adapters.ashby import AshbyAdapter
from app.crawlers.models import CrawledJob
from app.services.jobs.job_ingestion_service import JobIngestionService


def _canned_jobs() -> list[CrawledJob]:
    return [
        CrawledJob(title="Engineer", company="Acme", description="desc",
                   external_job_id="1", source_platform="ashby"),
        CrawledJob(title="Analyst", company="Acme", description="desc",
                   external_job_id="2", source_platform="ashby"),
    ]


class _FakeRepo:
    def __init__(self, result: dict[str, int] | None = None):
        self.result = result or {"discovered": 2, "inserted": 2, "updated": 0,
                                 "unchanged": 0, "deduplicated": 0, "skipped": 0}
        self.upsert_thread: int | None = None
        self.deactivate_threads: list[int] = []
        self.calls: list[str] = []

    def upsert_jobs(self, jobs: list) -> dict[str, int]:
        self.upsert_thread = threading.get_ident()
        return dict(self.result)

    def deactivate_not_seen_since(self, **kwargs: Any) -> int:
        self.deactivate_threads.append(threading.get_ident())
        self.calls.append("not_seen")
        return 1

    def deactivate_stale_jobs(self, **kwargs: Any) -> int:
        self.deactivate_threads.append(threading.get_ident())
        self.calls.append("stale")
        return 2


class _FakeService:
    def normalize_and_classify(self, job: CrawledJob) -> CrawledJob:
        return job


@pytest.mark.asyncio
async def test_upsert_runs_off_event_loop_thread(monkeypatch):
    """ingest_* must not execute sync upsert on the loop thread; result propagates."""
    async def _discover(self) -> list[CrawledJob]:
        return _canned_jobs()

    monkeypatch.setattr(AshbyAdapter, "discover_jobs", _discover)
    repo = _FakeRepo()
    ingestion = JobIngestionService(job_repository=repo, job_service=_FakeService())

    result = await ingestion.ingest_ashby_jobs("notion")

    assert result["inserted"] == 2
    assert repo.upsert_thread is not None
    assert repo.upsert_thread != threading.get_ident()


@pytest.mark.asyncio
async def test_upsert_exception_propagates(monkeypatch):
    """Upsert failure must still fail the ingest call (retry behavior preserved)."""
    async def _discover(self) -> list[CrawledJob]:
        return _canned_jobs()

    monkeypatch.setattr(AshbyAdapter, "discover_jobs", _discover)

    def _boom(jobs: list) -> dict[str, int]:
        raise RuntimeError("supabase down")

    repo = _FakeRepo()
    repo.upsert_jobs = _boom
    ingestion = JobIngestionService(job_repository=repo, job_service=_FakeService())

    with pytest.raises(RuntimeError, match="supabase down"):
        await ingestion.ingest_ashby_jobs("notion")


@pytest.mark.asyncio
async def test_crawl_job_deactivation_off_loop_success_shape(monkeypatch):
    """Full crawl_company_job: deactivation off-loop, ordering + result shape intact."""
    import app.workers.jobs.crawl_jobs as crawl_jobs

    repo = _FakeRepo()

    class _FakeIngestion:
        def __init__(self) -> None:
            self.job_repository = repo

        async def ingest_ashby_jobs(self, slug: str) -> dict[str, int]:
            return {"discovered": 2, "inserted": 2, "updated": 0,
                    "unchanged": 0, "deduplicated": 0, "skipped": 0}

    statuses: list[dict[str, Any]] = []

    async def _record(source: str, slug: str, payload: dict[str, Any]) -> None:
        statuses.append(payload)

    monkeypatch.setattr(crawl_jobs, "JobIngestionService", _FakeIngestion)
    monkeypatch.setattr(crawl_jobs, "_record_crawl_status", _record)

    out = await crawl_jobs.crawl_company_job({"job_id": "test-1"}, "ashby", "notion")

    assert out["success"] is True
    assert out["source"] == "ashby" and out["slug"] == "notion"
    assert out["deactivated"] == 3  # 1 not-seen + 2 stale
    assert out["deactivated_not_seen"] == 1
    assert repo.calls == ["not_seen", "stale"]  # ordering preserved
    assert repo.deactivate_threads and all(
        t != threading.get_ident() for t in repo.deactivate_threads
    )
    assert statuses and statuses[-1]["status"] == "success"


@pytest.mark.asyncio
async def test_crawl_job_ingest_failure_status_behavior(monkeypatch):
    """Ingest failure must raise and record a failed status (unchanged behavior)."""
    import app.workers.jobs.crawl_jobs as crawl_jobs

    class _FailingIngestion:
        def __init__(self) -> None:
            self.job_repository = _FakeRepo()

        async def ingest_ashby_jobs(self, slug: str) -> dict[str, int]:
            raise ValueError("bad source")

    statuses: list[dict[str, Any]] = []

    async def _record(source: str, slug: str, payload: dict[str, Any]) -> None:
        statuses.append(payload)

    monkeypatch.setattr(crawl_jobs, "JobIngestionService", _FailingIngestion)
    monkeypatch.setattr(crawl_jobs, "_record_crawl_status", _record)

    with pytest.raises(ValueError, match="bad source"):
        await crawl_jobs.crawl_company_job({"job_id": "test-2"}, "ashby", "notion")
    assert statuses and statuses[-1]["status"] == "failed"
