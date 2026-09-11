"""Upstash request-budget regression tests (no live Redis required).

Locks in the audit findings:

* one idle worker's cost is ``86400 / poll_delay`` ZRANGEBYSCORE/day;
* the default ``poll_delay`` must keep a month of idle polling comfortably
  inside the 500k Upstash budget;
* the scheduler must resolve per-provider cadences (24h) instead of the
  legacy 6h-everything default;
* the dispatcher must reuse the shared pool (no per-enqueue create/close).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.workers.redis_budget import (
    estimate_enqueue_requests,
    estimate_idle_requests_per_day,
    estimate_idle_requests_per_month,
    estimate_job_execution_requests,
)

UPSTASH_MONTHLY_BUDGET = 500_000


def test_idle_model_matches_arq_polling_math():
    # 0.5s legacy default: 172,800 polls/day (+48 health cmds) — over budget.
    legacy = estimate_idle_requests_per_day(0.5)
    assert legacy == pytest.approx(172_800 + 48, rel=1e-6)
    assert estimate_idle_requests_per_month(0.5) > UPSTASH_MONTHLY_BUDGET * 10


def test_default_poll_delay_fits_budget_with_headroom():
    from app.workers.settings import WorkerSettings

    assert WorkerSettings.poll_delay == pytest.approx(10.0)
    monthly = estimate_idle_requests_per_month(float(WorkerSettings.poll_delay))
    # Must fit COMFORTABLY: under 60% of budget for idle alone, leaving room
    # for real jobs, retries, scheduler passes, and health checks.
    assert monthly < UPSTASH_MONTHLY_BUDGET * 0.6


def test_poll_delay_env_override(monkeypatch):
    monkeypatch.setenv("ARQ_POLL_DELAY_SECONDS", "2.5")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        assert get_settings().arq_poll_delay_seconds == pytest.approx(2.5)
    finally:
        get_settings.cache_clear()


def test_health_check_interval_stays_hourly():
    from app.workers.settings import WorkerSettings

    assert WorkerSettings.health_check_interval == 3600


def test_scheduler_defaults_to_per_provider_cadence():
    from app.services.jobs.scheduled_crawl_runner import ScheduledCrawlRunner

    runner = ScheduledCrawlRunner()
    assert runner.interval_hours is None
    # Per-provider settings cadence (24h) applies when no override is set.
    assert runner._interval_for("yc") == pytest.approx(24.0)
    assert runner._interval_for("aggregator") == pytest.approx(24.0)


def test_scheduler_legacy_override_still_wins(monkeypatch):
    from app.config import get_settings
    from app.services.jobs.scheduled_crawl_runner import ScheduledCrawlRunner

    get_settings.cache_clear()
    monkeypatch.setenv("CRAWL_INTERVAL_HOURS", "6")
    try:
        runner = ScheduledCrawlRunner()
        assert runner._interval_for("yc") == pytest.approx(6.0)
    finally:
        get_settings.cache_clear()


def test_scheduler_target_count_bounds_daily_enqueue_cost():
    from app.crawlers.crawl_registry import all_targets

    targets = all_targets()
    # 1 YC + 6 firecrawl + 5 ATS + 2 aggregator = 14 crawl enqueues/day
    # at the intended 24h cadence (was 56/day under the 6h shadowing bug).
    assert len(targets) == 14
    daily_enqueue = len(targets) * estimate_enqueue_requests(with_lock=True)
    assert daily_enqueue <= 100  # negligible vs ~8.6k/day idle polling


def test_job_execution_cost_is_bounded():
    assert estimate_job_execution_requests() <= 12
    assert estimate_job_execution_requests(records_crawl_status=True) <= 13


@pytest.mark.asyncio
async def test_dispatcher_reuses_shared_pool_without_closing():
    from app.workers import dispatcher
    from app.workers.registry import clear_registry

    clear_registry()
    import importlib

    from app.workers import functions
    from app.workers.jobs import crawl_jobs

    importlib.reload(functions)
    importlib.reload(crawl_jobs)

    shared = AsyncMock()
    shared.enqueue_job = AsyncMock(
        return_value=type("J", (), {"job_id": "jid"})()
    )
    shared.set = AsyncMock(return_value=True)
    shared.aclose = AsyncMock()

    with patch(
        "app.workers.dispatcher._get_redis", return_value=shared
    ) as get_redis:
        job_id = await dispatcher.enqueue("careeros_worker_health")
        assert job_id == "jid"
        crawl_id = await dispatcher.enqueue_crawl_company("greenhouse", "stripe")
        assert crawl_id == "jid"
        assert get_redis.await_count == 2
    # Shared pool must NOT be closed by enqueue calls.
    shared.aclose.assert_not_awaited()


def test_worker_registers_expected_five_functions():
    # Self-contained: other test modules clear/reload the global registry
    # (test_dispatcher) and reload worker settings with whatever registry
    # state happens to exist (test_redis_config), so the already-imported
    # WorkerSettings.functions attribute is order-dependent. Re-register
    # from production modules here and assert the contract directly.
    import importlib

    from app.workers import registry

    registry.clear_registry()
    from app.workers import functions as _functions
    from app.workers.jobs import (
        crawl_jobs as _crawl_jobs,
    )
    from app.workers.jobs import (
        interview_prep_jobs as _interview_prep_jobs,
    )
    from app.workers.jobs import (
        job_intelligence_job as _job_intelligence_job,
    )

    importlib.reload(_functions)
    importlib.reload(_crawl_jobs)
    importlib.reload(_interview_prep_jobs)
    importlib.reload(_job_intelligence_job)

    names = {j.name for j in registry.get_registered_jobs()}
    assert {
        "careeros_worker_health",
        "parse_resume_job",
        "crawl_company_job",
        "generate_interview_prep_job",
        "analyze_job_intelligence",
    } <= names
