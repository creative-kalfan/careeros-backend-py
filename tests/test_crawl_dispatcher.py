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
