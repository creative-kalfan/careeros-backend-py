"""Regression tests for cooperative cancellation, active crawls gauge safety, and memory cleanup."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.crawlers.models import CrawledJob
from app.db.supabase import call_serialized, reset_persistence_semaphore, PersistenceCancelledError
from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository
from app.services.jobs.job_ingestion_service import JobIngestionService
import app.workers.jobs.crawl_jobs as crawl_jobs_mod


def _make_crawl_env(monkeypatch: Any, stage_to_cancel: str):
    """Set up crawl_company_job dependencies with a cancellation at a specific stage."""
    ingestion = MagicMock()
    repo = MagicMock()
    ingestion.job_repository = repo

    if stage_to_cancel == "provider":
        ingestion.ingest_ashby_jobs = AsyncMock(side_effect=asyncio.CancelledError("timeout in provider"))
    else:
        ingestion.ingest_ashby_jobs = AsyncMock(return_value={
            "discovered": 2, "inserted": 1, "updated": 0, "unchanged": 1,
            "deduplicated": 0, "skipped": 0,
        })

    if stage_to_cancel == "deactivation":
        def _cancel_deact(*args, **kwargs):
            raise asyncio.CancelledError("timeout in deactivation")
        monkeypatch.setattr(crawl_jobs_mod, "_deactivate_after_success", _cancel_deact)
    else:
        monkeypatch.setattr(crawl_jobs_mod, "_deactivate_after_success", lambda *a, **k: (0, 0, 0, 0))

    if stage_to_cancel == "event":
        mock_bus = MagicMock()
        mock_bus.publish = AsyncMock(side_effect=asyncio.CancelledError("timeout in event bus"))
        monkeypatch.setattr("app.events.get_event_bus", lambda: mock_bus)
    else:
        mock_bus = MagicMock()
        mock_report = MagicMock()
        mock_report.succeeded = True
        mock_bus.publish = AsyncMock(return_value=mock_report)
        monkeypatch.setattr("app.events.get_event_bus", lambda: mock_bus)

    if stage_to_cancel == "status":
        monkeypatch.setattr(crawl_jobs_mod, "_record_crawl_status", AsyncMock(side_effect=asyncio.CancelledError("timeout in status")))
    else:
        monkeypatch.setattr(crawl_jobs_mod, "_record_crawl_status", AsyncMock())

    monkeypatch.setattr(crawl_jobs_mod, "JobIngestionService", lambda *a, **k: ingestion)
    return crawl_jobs_mod


@pytest.mark.asyncio
async def test_active_crawls_gauge_never_leaks_on_provider_cancellation(monkeypatch):
    """_ACTIVE_CRAWLS must be 0 after cancellation in provider discovery."""
    mod = _make_crawl_env(monkeypatch, "provider")
    with pytest.raises(asyncio.CancelledError):
        await mod.crawl_company_job({"job_id": "test-1"}, "ashby", "company-1")
    assert mod.active_crawl_count() == 0


@pytest.mark.asyncio
async def test_active_crawls_gauge_never_leaks_on_deactivation_cancellation(monkeypatch):
    """_ACTIVE_CRAWLS must be 0 after cancellation in deactivation phase."""
    mod = _make_crawl_env(monkeypatch, "deactivation")
    with pytest.raises(asyncio.CancelledError):
        await mod.crawl_company_job({"job_id": "test-2"}, "ashby", "company-2")
    assert mod.active_crawl_count() == 0


@pytest.mark.asyncio
async def test_active_crawls_gauge_never_leaks_on_event_dispatch_cancellation(monkeypatch):
    """_ACTIVE_CRAWLS must be 0 after cancellation in event dispatch phase."""
    mod = _make_crawl_env(monkeypatch, "event")
    with pytest.raises(asyncio.CancelledError):
        await mod.crawl_company_job({"job_id": "test-3"}, "ashby", "company-3")
    assert mod.active_crawl_count() == 0


@pytest.mark.asyncio
async def test_call_serialized_aborts_immediately_on_cancel_event():
    """call_serialized must not execute and must raise PersistenceCancelledError when cancel_event is set."""
    cancel_ev = threading.Event()
    cancel_ev.set()
    executed = False

    def _should_not_run():
        nonlocal executed
        executed = True

    with pytest.raises(PersistenceCancelledError):
        call_serialized(_should_not_run, cancel_event=cancel_ev)

    assert executed is False


@pytest.mark.asyncio
async def test_call_serialized_aborts_waiting_threads_on_cancel_event():
    """Queued threads waiting for semaphore abort immediately when their cancel_event is set."""
    reset_persistence_semaphore(1)
    ev_holding = threading.Event()
    ev_waiter_cancel = threading.Event()
    waiter_aborted = threading.Event()

    def _long_hold():
        ev_holding.set()
        import time
        time.sleep(0.5)

    def _waiter():
        try:
            call_serialized(lambda: None, cancel_event=ev_waiter_cancel)
        except PersistenceCancelledError:
            waiter_aborted.set()

    t1 = threading.Thread(target=lambda: call_serialized(_long_hold))
    t2 = threading.Thread(target=_waiter)

    t1.start()
    ev_holding.wait(timeout=2.0)

    t2.start()
    # While t2 is waiting for semaphore, cancel it
    ev_waiter_cancel.set()

    # t2 should abort almost immediately (within 0.3s) without waiting for t1 to release after 0.5s
    t2.join(timeout=1.0)
    assert waiter_aborted.is_set()

    t1.join(timeout=2.0)


@pytest.mark.asyncio
async def test_upsert_jobs_checks_cancel_event_before_db():
    """upsert_jobs checks cancel_event and exits without writing."""
    repo = JobRepository.__new__(JobRepository)
    cancel_ev = threading.Event()
    cancel_ev.set()

    job = NormalizedJob(
        title="Test Engineer",
        company="TestCorp",
        source_platform="ashby",
        external_job_id="test-ext-1",
    )
    with pytest.raises(PersistenceCancelledError):
        repo.upsert_jobs([job], cancel_event=cancel_ev)


@pytest.mark.asyncio
async def test_raw_payload_freed_before_persist():
    """_persist_offloop sets job.raw = None to prevent memory accumulation."""
    service = JobIngestionService.__new__(JobIngestionService)
    repo = MagicMock()
    repo.upsert_jobs.return_value = {"inserted": 1, "updated": 0}
    service.job_repository = repo

    job = NormalizedJob(
        title="Software Engineer",
        company="Acme",
        source_platform="greenhouse",
        external_job_id="123",
        raw={"huge": "payload" * 500},
    )
    assert job.raw is not None

    await service._persist_offloop([job])
    assert job.raw is None


@pytest.mark.asyncio
async def test_async_persistence_slot_bounds_concurrency_and_releases():
    """async_persistence_slot bounds concurrent holders and releases properly."""
    from app.db.supabase import async_persistence_slot, reset_persistence_semaphore

    reset_persistence_semaphore(2)
    active = 0
    max_active = 0

    async def _worker():
        nonlocal active, max_active
        async with async_persistence_slot():
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1

    await asyncio.gather(*[_worker() for _ in range(5)])
    assert max_active == 2
    assert active == 0


@pytest.mark.asyncio
async def test_async_persistence_slot_aborts_on_cancel_event():
    """async_persistence_slot raises PersistenceCancelledError when cancel_event is set."""
    from app.db.supabase import async_persistence_slot, PersistenceCancelledError

    ev = threading.Event()
    ev.set()
    with pytest.raises(PersistenceCancelledError):
        async with async_persistence_slot(cancel_event=ev):
            pass


@pytest.mark.asyncio
async def test_async_persistence_slot_times_out():
    """async_persistence_slot raises PersistenceTimeoutError when acquisition deadline is exceeded."""
    from app.db.supabase import async_persistence_slot, reset_persistence_semaphore, PersistenceTimeoutError

    reset_persistence_semaphore(1)

    async def _holder():
        async with async_persistence_slot():
            await asyncio.sleep(0.5)

    holder_task = asyncio.create_task(_holder())
    await asyncio.sleep(0.02)

    with pytest.raises(PersistenceTimeoutError, match="waiting for persistence semaphore"):
        async with async_persistence_slot(timeout_seconds=0.1):
            pass

    await holder_task


@pytest.mark.asyncio
async def test_async_persistence_slot_releases_on_task_cancellation():
    """Cancelling a waiting coroutine cleanly releases slot and permits subsequent acquisitions."""
    from app.db.supabase import async_persistence_slot, reset_persistence_semaphore

    reset_persistence_semaphore(1)

    async def _holder():
        async with async_persistence_slot():
            await asyncio.sleep(0.1)

    t1 = asyncio.create_task(_holder())
    await asyncio.sleep(0.01)

    async def _waiter():
        async with async_persistence_slot():
            pass

    t2 = asyncio.create_task(_waiter())
    await asyncio.sleep(0.01)
    t2.cancel()

    with pytest.raises(asyncio.CancelledError):
        await t2

    await t1

    # After holder finishes, slot must be completely free
    executed = False
    async with async_persistence_slot(timeout_seconds=0.5):
        executed = True
    assert executed is True
