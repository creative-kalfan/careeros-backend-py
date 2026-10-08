"""GitHub Actions crawl tick: auth, bounded single tick, overlap safety, worker mode."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services.jobs import crawl_dispatcher

URL = "/internal/scheduler/crawl-tick"


def _client(monkeypatch, secret="s3cret", enabled=True, tick=None):
    from app.api.routes import internal_scheduler
    from app.main import app

    monkeypatch.setattr(internal_scheduler, "get_settings", lambda: SimpleNamespace(
        scheduler_trigger_secret=secret, job_crawl_enabled=enabled,
    ))
    tick = tick or AsyncMock(return_value={"enqueued": 2, "analysis_backfill_enqueued": 0})
    monkeypatch.setattr(crawl_dispatcher, "run_dispatch_tick", tick)
    return TestClient(app), tick


def test_valid_auth_runs_one_tick(monkeypatch):
    client, tick = _client(monkeypatch)
    res = client.post(URL, headers={"Authorization": "Bearer s3cret"})
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "enqueued": 2, "analysis_backfill_enqueued": 0}
    tick.assert_awaited_once()


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "s3cretx"}])
def test_invalid_auth_rejected(monkeypatch, headers):
    client, tick = _client(monkeypatch)
    assert client.post(URL, headers=headers).status_code == 401
    tick.assert_not_awaited()


def test_unconfigured_secret_disables_endpoint(monkeypatch):
    client, tick = _client(monkeypatch, secret="")
    assert client.post(URL, headers={"Authorization": "Bearer "}).status_code == 503
    tick.assert_not_awaited()


def test_crawl_kill_switch_skips_tick(monkeypatch):
    client, tick = _client(monkeypatch, enabled=False)
    res = client.post(URL, headers={"Authorization": "Bearer s3cret"})
    assert res.json()["status"] == "disabled"
    tick.assert_not_awaited()


def _tick_env(monkeypatch, *, in_flight=0, pool=None, capacity=2):
    """Real dispatch_due_targets with a fake SKIP LOCKED claim over a shared pool."""
    pool = list(pool or [])
    monkeypatch.setattr(crawl_dispatcher, "_migration_probe", lambda: True)
    monkeypatch.setattr(crawl_dispatcher, "_worker_capacity", lambda: capacity)
    monkeypatch.setattr(crawl_dispatcher, "_in_flight_crawls", AsyncMock(return_value=in_flight))
    monkeypatch.setattr(crawl_dispatcher, "get_settings", lambda: SimpleNamespace(
        dispatch_batch=2, crawl_lease_seconds=900, worker_soft_memory_limit_mb=10**9,
        heartbeat_url="",
    ))
    claims = []

    def claim(name, params):
        assert name == "claim_due_crawl_targets"
        taken = pool[: params["p_limit"]]
        del pool[: params["p_limit"]]
        claims.append(params)
        return taken

    monkeypatch.setattr(crawl_dispatcher, "_rpc", claim)
    enqueued = []

    async def enqueue(source, slug, run_id):
        await asyncio.sleep(0)
        enqueued.append(slug)
        return run_id

    import app.workers.dispatcher as dispatcher
    monkeypatch.setattr(dispatcher, "enqueue_scheduled_crawl", enqueue)
    monkeypatch.setattr(dispatcher, "_get_redis", AsyncMock(return_value=AsyncMock()))
    monkeypatch.setattr(crawl_dispatcher, "backfill_missing_intelligence", AsyncMock(return_value=0))
    monkeypatch.setattr(crawl_dispatcher, "check_crawl_slo", AsyncMock())
    return claims, enqueued


def _targets(n):
    return [{"source": "greenhouse", "slug": f"co{i}", "next_run_at": "2026-10-01T00:00:00+00:00"}
            for i in range(n)]


@pytest.mark.asyncio
async def test_tick_is_bounded_single_claim(monkeypatch):
    claims, enqueued = _tick_env(monkeypatch, pool=_targets(10))
    summary = await crawl_dispatcher.run_dispatch_tick({})
    assert summary["enqueued"] == 2
    assert len(claims) == 1 and claims[0]["p_limit"] == 2
    assert enqueued == ["co0", "co1"]


@pytest.mark.asyncio
async def test_tick_no_due_targets(monkeypatch):
    claims, enqueued = _tick_env(monkeypatch, pool=[])
    assert (await crawl_dispatcher.run_dispatch_tick({}))["enqueued"] == 0
    assert enqueued == []


@pytest.mark.asyncio
async def test_tick_respects_admission_backpressure(monkeypatch):
    claims, enqueued = _tick_env(monkeypatch, in_flight=2, pool=_targets(5))
    assert (await crawl_dispatcher.run_dispatch_tick({}))["enqueued"] == 0
    assert claims == [] and enqueued == []


@pytest.mark.asyncio
async def test_overlapping_ticks_never_enqueue_same_target(monkeypatch):
    claims, enqueued = _tick_env(monkeypatch, pool=_targets(3))
    await asyncio.gather(*(crawl_dispatcher.run_dispatch_tick({}) for _ in range(4)))
    assert sorted(enqueued) == ["co0", "co1", "co2"]


@pytest.mark.asyncio
async def test_github_mode_worker_starts_no_scheduler(monkeypatch):
    monkeypatch.setenv("JOB_CRAWL_ENABLED", "true")
    monkeypatch.setenv("LEGACY_APSCHEDULER_ENABLED", "true")
    monkeypatch.setenv("CRAWL_SCHEDULER_MODE", "github")
    monkeypatch.setenv("WORKER_CONSUME_ANALYSIS_QUEUE", "false")
    get_settings.cache_clear()
    from app.workers import settings as ws

    ws._crawl_runner = None
    ws._dispatcher_task = None
    try:
        await ws.worker_startup({})
        assert ws._crawl_runner is None
        assert ws._dispatcher_task is None
    finally:
        await ws.worker_shutdown({})
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_complete_target_probes_without_prior_dispatch(monkeypatch):
    """Worker in github mode never dispatches; completion must still persist."""
    calls = []
    monkeypatch.setattr(crawl_dispatcher, "_migration_probe", lambda: True)
    monkeypatch.setattr(crawl_dispatcher, "_rpc", lambda name, params: calls.append(name))
    monkeypatch.setattr(crawl_dispatcher, "get_settings", lambda: SimpleNamespace(
        crawl_min_interval_minutes=360, crawl_max_interval_minutes=2880,
        crawl_dead_after_failures=10, firecrawl_min_interval_hours=72,
    ))

    class Empty:
        def __getattr__(self, _name):
            return lambda *a, **k: self

        @property
        def data(self):
            return []

    monkeypatch.setattr(crawl_dispatcher, "get_service_client", lambda: Empty())
    await crawl_dispatcher.complete_target("greenhouse", "co0", True)
    assert calls == ["complete_crawl_target"]
