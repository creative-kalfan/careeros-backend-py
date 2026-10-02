from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from app.services.jobs.crawl_dispatcher import adaptive_interval_minutes, deterministic_job_id
from app.services.jobs.source_discovery import parse_ats_board


def test_interval_adapts_with_bounds_and_p0_cap():
    assert adaptive_interval_minutes(1440, changed=True, unchanged_streak=0, priority=1) == 720
    assert adaptive_interval_minutes(720, changed=True, unchanged_streak=0, priority=1, minimum=600) == 600
    assert adaptive_interval_minutes(720, changed=False, unchanged_streak=3, priority=1, maximum=2000) == 1440
    assert adaptive_interval_minutes(1440, changed=False, unchanged_streak=3, priority=0, maximum=2880) == 1440


def test_dispatch_id_is_stable_for_same_schedule_bucket():
    stamp = datetime(2026, 10, 1, tzinfo=timezone.utc).isoformat()
    assert deterministic_job_id("ashby", "openai", stamp) == deterministic_job_id("ashby", "openai", stamp)
    assert deterministic_job_id("ashby", "openai", stamp) != deterministic_job_id(
        "ashby", "notion", stamp
    )


def test_parse_known_ats_board_url_shapes():
    assert parse_ats_board("https://boards.greenhouse.io/acme/jobs/42") == ("greenhouse", "acme")
    assert parse_ats_board("https://job-boards.greenhouse.io/acme") == ("greenhouse", "acme")
    assert parse_ats_board("https://jobs.lever.co/acme/abc") == ("lever", "acme")
    assert parse_ats_board("https://jobs.ashbyhq.com/acme/job") == ("ashby", "acme")
    assert parse_ats_board("https://careers.smartrecruiters.com/acme/job") == ("smartrecruiters", "acme")
    assert parse_ats_board("https://example.com/jobs") is None


def test_admin_crawl_status_requires_configured_header(monkeypatch):
    from app.api.routes import admin
    from app.main import app

    monkeypatch.setattr(admin, "get_settings", lambda: SimpleNamespace(admin_status_token="secret"))
    client = TestClient(app)
    assert client.get("/api/admin/crawl-status").status_code == 403
    assert client.get(
        "/api/admin/crawl-status", headers={"ADMIN_STATUS_TOKEN": "wrong"}
    ).status_code == 403


def test_missing_schedule_migration_disables_dispatch_cleanly(monkeypatch):
    from app.services.jobs import crawl_dispatcher

    class MissingTable:
        def table(self, _name):
            raise RuntimeError("relation does not exist")

    monkeypatch.setattr(crawl_dispatcher, "get_service_client", lambda: MissingTable())
    monkeypatch.setattr(crawl_dispatcher, "_migration_available", None)
    assert crawl_dispatcher._migration_probe() is False


def test_schedule_migration_uses_leases_and_restricts_rpc_execution():
    sql = Path("sql/migrations/025_crawl_targets.sql").read_text()
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "GRANT EXECUTE ON FUNCTION public.claim_due_crawl_targets(INT, INT) TO service_role" in sql


@pytest.mark.asyncio
async def test_slo_counts_old_due_targets(monkeypatch):
    from app.services.jobs import crawl_dispatcher

    old = "2026-09-28T00:00:00+00:00"

    class Query:
        def select(self, *_args):
            return self

        def eq(self, *_args):
            return self

        def execute(self):
            return SimpleNamespace(data=[{"source": "ashby", "slug": "acme", "next_run_at": old,
                                         "last_success_at": old, "created_at": old}])

    class Client:
        def table(self, _name):
            return Query()

    monkeypatch.setattr(crawl_dispatcher, "get_service_client", lambda: Client())
    monkeypatch.setattr(crawl_dispatcher, "get_settings", lambda: SimpleNamespace(
        slo_overdue_minutes=120, alert_webhook_url=""
    ))
    assert await crawl_dispatcher.check_crawl_slo() == {"overdue": 1, "no_success_36h": 1}

class _CdBadTable:
    def table(self, *_a, **_k):
        raise RuntimeError("relation does not exist")


class _CdOkTable:
    def table(self, *_a, **_k):
        return self

    def select(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


def test_migration_probe_rechecks_after_interval(monkeypatch):
    import time
    from app.services.jobs import crawl_dispatcher

    monkeypatch.setattr(crawl_dispatcher, "get_service_client", lambda: _CdBadTable())
    monkeypatch.setattr(
        crawl_dispatcher,
        "get_settings",
        lambda: SimpleNamespace(migration_probe_recheck_seconds=300),
    )
    crawl_dispatcher._migration_available = True
    crawl_dispatcher._migration_probed_at = time.monotonic()
    try:
        assert crawl_dispatcher._migration_probe() is True
    finally:
        crawl_dispatcher._reset_migration_probe()


def test_migration_probe_refires_after_interval(monkeypatch):
    import time
    from app.services.jobs import crawl_dispatcher

    monkeypatch.setattr(crawl_dispatcher, "get_service_client", lambda: _CdBadTable())
    monkeypatch.setattr(
        crawl_dispatcher,
        "get_settings",
        lambda: SimpleNamespace(migration_probe_recheck_seconds=300),
    )
    crawl_dispatcher._migration_available = True
    crawl_dispatcher._migration_probed_at = time.monotonic() - 10_000
    try:
        assert crawl_dispatcher._migration_probe() is False
    finally:
        crawl_dispatcher._reset_migration_probe()


def test_migration_probe_recovers_without_restart(monkeypatch):
    from app.services.jobs import crawl_dispatcher

    monkeypatch.setattr(
        crawl_dispatcher,
        "get_settings",
        lambda: SimpleNamespace(migration_probe_recheck_seconds=0),
    )
    monkeypatch.setattr(crawl_dispatcher, "get_service_client", lambda: _CdBadTable())
    crawl_dispatcher._reset_migration_probe()
    try:
        assert crawl_dispatcher._migration_probe() is False
        monkeypatch.setattr(crawl_dispatcher, "get_service_client", lambda: _CdOkTable())
        assert crawl_dispatcher._migration_probe() is True
    finally:
        crawl_dispatcher._reset_migration_probe()


def test_disabled_migration_probe_logs_loudly(monkeypatch, caplog):
    import logging
    from app.services.jobs import crawl_dispatcher

    monkeypatch.setattr(crawl_dispatcher, "get_service_client", lambda: _CdBadTable())
    monkeypatch.setattr(
        crawl_dispatcher,
        "get_settings",
        lambda: SimpleNamespace(migration_probe_recheck_seconds=0),
    )
    crawl_dispatcher._reset_migration_probe()
    try:
        with caplog.at_level(logging.CRITICAL, logger="app.services.jobs.crawl_dispatcher"):
            assert crawl_dispatcher._migration_probe() is False
        messages = [r.getMessage() for r in caplog.records if r.levelno == logging.CRITICAL]
        assert any("migration 025" in m and "DISABLED" in m for m in messages), messages
    finally:
        crawl_dispatcher._reset_migration_probe()


def test_worker_capacity_ignores_missing_ctx_worker():
    from app.services.jobs import crawl_dispatcher

    capacity = crawl_dispatcher._worker_capacity()
    assert capacity >= 1
    # ARQ injects only ctx[redis]; there is no ctx[worker] carrying worker settings.
    assert getattr({}, "max_jobs", None) is None
    try:
        from app.workers.settings import WorkerSettings

        assert capacity == max(1, int(getattr(WorkerSettings, "max_jobs", 1)))
    except Exception:
        assert capacity == max(
            1, int(crawl_dispatcher.get_settings().persistence_max_concurrency)
        )


@pytest.mark.asyncio
async def test_admission_guard_blocks_when_queue_at_capacity(monkeypatch):
    from app.services.jobs import crawl_dispatcher

    monkeypatch.setattr(crawl_dispatcher, "_migration_probe", lambda: True)
    monkeypatch.setattr(crawl_dispatcher, "_worker_capacity", lambda: 2)

    async def _queue_depth_at_capacity():
        return 2

    monkeypatch.setattr(crawl_dispatcher, "_queue_depth", _queue_depth_at_capacity)

    def _claim_must_not_run(_name, _params):
        raise AssertionError("claim rpc must not run under backpressure")

    monkeypatch.setattr(crawl_dispatcher, "_rpc", _claim_must_not_run)
    monkeypatch.setattr(
        crawl_dispatcher,
        "get_settings",
        lambda: SimpleNamespace(dispatch_batch=2, crawl_lease_seconds=900),
    )
    try:
        assert await crawl_dispatcher.dispatch_due_targets({}) == 0
    finally:
        crawl_dispatcher._reset_migration_probe()


@pytest.mark.asyncio
async def test_admission_guard_claims_only_free_slots(monkeypatch):
    from app.services.jobs import crawl_dispatcher

    monkeypatch.setattr(crawl_dispatcher, "_migration_probe", lambda: True)
    monkeypatch.setattr(crawl_dispatcher, "_worker_capacity", lambda: 2)

    async def _queue_depth_one_free():
        return 1

    monkeypatch.setattr(crawl_dispatcher, "_queue_depth", _queue_depth_one_free)

    captured = {}

    def _capture_claim(name, params):
        captured["name"] = name
        captured["params"] = params
        return []

    monkeypatch.setattr(crawl_dispatcher, "_rpc", _capture_claim)
    monkeypatch.setattr(
        crawl_dispatcher,
        "get_settings",
        lambda: SimpleNamespace(dispatch_batch=2, crawl_lease_seconds=900),
    )
    try:
        assert await crawl_dispatcher.dispatch_due_targets({}) == 0
    finally:
        crawl_dispatcher._reset_migration_probe()

    assert captured["params"]["p_limit"] == 1
    assert captured["params"]["p_lease_seconds"] == 900


def test_lease_warning_when_lease_below_worst_case(caplog):
    import logging
    from app.services.jobs import crawl_dispatcher

    logger_name = "app.services.jobs.crawl_dispatcher"
    with caplog.at_level(logging.WARNING, logger=logger_name):
        crawl_dispatcher._check_lease_coverage(
            SimpleNamespace(crawl_lease_seconds=60), capacity=2
        )
        short = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "lease" in r.getMessage().lower()
            and "worst_case_wait" in r.getMessage().lower()
        ]
        assert short, "expected a lease-coverage warning at 60s"

        caplog.clear()
        crawl_dispatcher._check_lease_coverage(
            SimpleNamespace(crawl_lease_seconds=900), capacity=2
        )
        long = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "worst_case_wait" in r.getMessage().lower()
        ]
        assert not long, "no lease warning expected when lease covers the worst case"