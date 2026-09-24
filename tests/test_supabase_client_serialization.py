"""Shared sync Supabase client must never be driven concurrently by threads."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from app.crawlers.adapters.ashby import AshbyAdapter
from app.crawlers.models import CrawledJob
from app.db.supabase import call_serialized
from app.services.jobs.job_ingestion_service import JobIngestionService


class _OverlapTracker:
    """Records peak concurrency of a guarded section (barrier forces overlap)."""

    def __init__(self) -> None:
        self.arrival = threading.Barrier(2)
        self._guard = threading.Lock()
        self.active = 0
        self.max_active = 0

    def section(self) -> None:
        with self._guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self._guard:
            self.active -= 1

    def racer(self, guarded: bool) -> None:
        # Barrier first (outside the client lock) forces both OS threads to
        # arrive together; then the guarded section must still serialize.
        self.arrival.wait(timeout=10)
        if guarded:
            call_serialized(self.section)
        else:
            self.section()


@pytest.mark.asyncio
async def test_concurrent_guarded_sections_serialize_on_real_threads():
    """Two to_thread workers through call_serialized never overlap (deterministic)."""
    tracker = _OverlapTracker()
    await asyncio.gather(
        asyncio.to_thread(tracker.racer, True),
        asyncio.to_thread(tracker.racer, True),
    )
    assert tracker.max_active == 1


@pytest.mark.asyncio
async def test_harness_detects_overlap_without_guard():
    """Control: same overlap without the lock reaches 2 (test is sensitive)."""
    tracker = _OverlapTracker()
    await asyncio.gather(
        asyncio.to_thread(tracker.racer, False),
        asyncio.to_thread(tracker.racer, False),
    )
    assert tracker.max_active == 2


@pytest.mark.asyncio
async def test_concurrent_ingests_serialize_upsert_and_keep_results(monkeypatch):
    """Two concurrent crawls serialize persistence; results intact."""
    active = 0
    max_active = 0
    guard = threading.Lock()

    async def _discover(self: Any) -> list[CrawledJob]:
        return [CrawledJob(title="E", company="A", description="d",
                            external_job_id="1", source_platform="ashby")]

    def _upsert(jobs: list) -> dict[str, int]:
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            return {"discovered": 1, "inserted": 1, "updated": 0,
                    "unchanged": 0, "deduplicated": 0, "skipped": 0}
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(AshbyAdapter, "discover_jobs", _discover)

    class _Svc:
        def normalize_and_classify(self, job: CrawledJob) -> CrawledJob:
            return job

    def _make() -> JobIngestionService:
        ingestion = JobIngestionService(job_repository=object(), job_service=_Svc())
        ingestion.job_repository = type("R", (), {"upsert_jobs": staticmethod(_upsert)})()
        return ingestion

    out = await asyncio.gather(
        _make().ingest_ashby_jobs("a"), _make().ingest_ashby_jobs("b")
    )
    assert [r["inserted"] for r in out] == [1, 1]
    assert max_active == 1


@pytest.mark.asyncio
async def test_upsert_still_uses_to_thread(monkeypatch):
    """asyncio.to_thread remains in the persistence path (loop stays unblocked)."""
    import asyncio as aio

    calls: list[str] = []
    orig = aio.to_thread

    async def _spy(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
        calls.append(getattr(fn, "__name__", repr(fn)))
        return await orig(fn, *args, **kwargs)

    async def _discover(self: Any) -> list[CrawledJob]:
        return []

    monkeypatch.setattr(AshbyAdapter, "discover_jobs", _discover)
    monkeypatch.setattr(aio, "to_thread", _spy)

    class _Repo:
        def upsert_jobs(self, jobs: list) -> dict[str, int]:
            return {"discovered": 0, "inserted": 0, "updated": 0,
                    "unchanged": 0, "deduplicated": 0, "skipped": 0}

    class _Svc:
        def normalize_and_classify(self, job: CrawledJob) -> CrawledJob:
            return job

    ingestion = JobIngestionService(job_repository=_Repo(), job_service=_Svc())
    await ingestion.ingest_ashby_jobs("notion")
    assert "call_serialized" in calls


@pytest.mark.asyncio
async def test_loop_stays_responsive_during_blocking_persist(monkeypatch):
    """Ticker advances while a 0.4s blocking persist runs (would stall ~1.4s on-loop)."""
    import time as _t

    async def _discover(self: Any) -> list[CrawledJob]:
        return [CrawledJob(title="E", company="A", description="d",
                            external_job_id="1", source_platform="ashby")]

    def _slow_upsert(jobs: list) -> dict[str, int]:
        _t.sleep(0.4)
        return {"discovered": 1, "inserted": 1, "updated": 0,
                "unchanged": 0, "deduplicated": 0, "skipped": 0}

    monkeypatch.setattr(AshbyAdapter, "discover_jobs", _discover)

    class _Svc:
        def normalize_and_classify(self, job: CrawledJob) -> CrawledJob:
            return job

    ingestion = JobIngestionService(job_repository=object(), job_service=_Svc())
    ingestion.job_repository = type("R", (), {"upsert_jobs": staticmethod(_slow_upsert)})()

    ticks = 0

    async def _ticker() -> None:
        nonlocal ticks
        for _ in range(20):
            await asyncio.sleep(0.05)
            ticks += 1

    start = _t.monotonic()
    await asyncio.gather(ingestion.ingest_ashby_jobs("x"), _ticker())
    elapsed = _t.monotonic() - start
    assert ticks == 20
    assert elapsed < 1.25
