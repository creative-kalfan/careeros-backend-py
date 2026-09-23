"""Worker owns the crawler scheduler via ARQ lifecycle hooks."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_worker_settings_wires_startup_shutdown():
    from app.workers.settings import WorkerSettings, worker_shutdown, worker_startup

    assert WorkerSettings.on_startup is worker_startup
    assert WorkerSettings.on_shutdown is worker_shutdown


@pytest.mark.asyncio
async def test_worker_startup_starts_scheduler_with_imminent_first_run(monkeypatch):
    monkeypatch.setenv("JOB_CRAWL_ENABLED", "true")
    get_settings.cache_clear()
    from app.workers import settings as ws

    ws._crawl_runner = None
    await ws.worker_startup({})
    try:
        assert ws._crawl_runner is not None
        sched = ws._crawl_runner._scheduler
        assert sched is not None
        jobs = sched.get_jobs()
        assert jobs
        now = datetime.now(timezone.utc)
        for job in jobs:
            assert job.next_run_time is not None
            assert (job.next_run_time - now).total_seconds() < 3600
    finally:
        await ws.worker_shutdown({})
    assert ws._crawl_runner is None


@pytest.mark.asyncio
async def test_worker_startup_respects_disabled_flag(monkeypatch, caplog):
    monkeypatch.setenv("JOB_CRAWL_ENABLED", "false")
    get_settings.cache_clear()
    from app.workers import settings as ws

    ws._crawl_runner = None
    with caplog.at_level("INFO"):
        await ws.worker_startup({})
    assert ws._crawl_runner is None
