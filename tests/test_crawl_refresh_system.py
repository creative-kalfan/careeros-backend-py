"""Tests for the daily job-refresh system.

Covers: crawl registry structure/priorities, scheduler enable-flag filtering,
deactivate_not_seen_since scoping, and crawl success/failure lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.crawlers.crawl_registry import (
    FIRECRAWL_TARGETS,
    YC_TARGET,
    all_targets,
    targets_for_provider,
)
from app.repositories.job_repository import JobRepository
from app.services.jobs.scheduled_crawl_runner import ScheduledCrawlRunner


def _set_setting(monkeypatch, name, value):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, name, value, raising=False)


def _run(coro):
    import asyncio

    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_contains_all_provider_families():
    assert {t.provider for t in all_targets()} == {"yc", "firecrawl", "ats", "aggregator"}


def test_registry_priority_order_yc_first():
    targets = all_targets()
    priorities = [t.priority for t in targets]
    assert priorities == sorted(priorities)
    assert targets[0].source == "ycombinator"
    idx = {t.source: i for i, t in enumerate(targets)}
    assert idx["firecrawl"] < idx["ashby"] < idx["adzuna"]


def test_yc_is_single_high_priority_target():
    yc = targets_for_provider("yc")
    assert len(yc) == 1 and yc[0] is YC_TARGET and YC_TARGET.priority == 1


def test_firecrawl_targets_use_careers_url_slug_format():
    for t in FIRECRAWL_TARGETS:
        company, sep, careers_url = t.slug.partition("|")
        assert sep == "|" and company and careers_url.startswith("http")


# ---------------------------------------------------------------------------
# deactivate_not_seen_since (repository) — chainable query stub
# ---------------------------------------------------------------------------


class _Query:
    def __init__(self, applied):
        self._applied = applied

    def select(self, *_):
        return self

    def eq(self, field, value):
        self._applied.append(("eq", field, value))
        return self

    def lt(self, field, value):
        self._applied.append(("lt", field, value))
        return self

    def execute(self):
        result = MagicMock()
        result.data = [{"id": "job-1"}, {"id": "job-2"}]
        return result

    def update(self, _values):
        self._applied.append(("update", None, None))
        return self

    def range(self, *a):
        return self

    def order(self, *a, **kw):
        return self


class _FakeClient:
    """Returns one shared _Query for selects; records updates."""

    def __init__(self):
        self.applied: list = []

    def table(self, name):
        self._name = name
        return _Query(self.applied)

    def __getattr__(self, item):
        # Any other method (update chains etc.) returns a chainable no-op.
        def _noop(*a, **kw):
            return self

        return _noop


def _make_repo() -> tuple[JobRepository, _FakeClient]:
    client = _FakeClient()
    repo = JobRepository(client=client)
    repo._has_last_seen_at = True  # skip column probe
    return repo, client


# ---------------------------------------------------------------------------
# deactivate_not_seen_since scoping
# ---------------------------------------------------------------------------


def test_deactivate_not_seen_since_filters_and_counts():
    repo, client = _make_repo()

    count = repo.deactivate_not_seen_since(
        source_platform="firecrawl",
        since_iso="2026-01-01T00:00:00+00:00",
        careers_url="https://posthog.com/careers",
    )

    assert count == 2
    triples = {(op, f, v) for (op, f, v) in client.applied if op == "eq"}
    assert ("eq", "is_active", True) in triples
    assert ("eq", "source_platform", "firecrawl") in triples
    assert ("eq", "careers_url", "https://posthog.com/careers") in triples
    assert any(op == "lt" and f == "last_seen_at" for (op, f, _) in client.applied)


def test_deactivate_not_seen_since_no_careers_scope_without_url():
    repo, client = _make_repo()

    repo.deactivate_not_seen_since(
        source_platform="ycombinator", since_iso="2026-01-01T00:00:00+00:00"
    )

    assert not any(f == "careers_url" for (_, f, _) in client.applied)


def test_deactivate_not_seen_since_disabled_without_last_seen_column():
    repo, client = _make_repo()
    repo._has_last_seen_at = False

    assert repo.deactivate_not_seen_since("adzuna", "2026-01-01T00:00:00+00:00") == 0
    assert client.applied == []


# ---------------------------------------------------------------------------
# crawl_company_job lifecycle
# ---------------------------------------------------------------------------


class _FakeRepo:
    def __init__(self):
        self.not_seen_calls: list[dict] = []
        self.stale_calls: list[dict] = []

    def deactivate_not_seen_since(self, **kwargs):
        self.not_seen_calls.append(kwargs)
        return 3

    def deactivate_stale_jobs(self, **kwargs):
        self.stale_calls.append(kwargs)
        return 1


def _patch_ingestion(monkeypatch, fake_repo, method, side_effect):
    from app.workers.jobs import crawl_jobs

    fake_ingestion = MagicMock()
    fake_ingestion.job_repository = fake_repo
    if isinstance(side_effect, Exception):
        mock = AsyncMock(side_effect=side_effect)
    else:
        mock = AsyncMock(return_value=side_effect)
    setattr(fake_ingestion, method, mock)
    monkeypatch.setattr(
        crawl_jobs.JobIngestionService, "__new__", lambda cls, *a, **kw: fake_ingestion
    )
    monkeypatch.setattr(crawl_jobs, "_record_crawl_status", AsyncMock())
    return crawl_jobs


@pytest.mark.asyncio
async def test_successful_crawl_runs_reconciliation(monkeypatch):
    fake_repo = _FakeRepo()
    crawl_jobs = _patch_ingestion(
        monkeypatch, fake_repo, "ingest_ycombinator_jobs",
        {"discovered": 5, "inserted": 2, "updated": 1, "unchanged": 2,
         "deduplicated": 0, "skipped": 0},
    )

    result = await crawl_jobs.crawl_company_job({"job_id": "t"}, "ycombinator", "")

    assert result["success"] is True
    assert result["deactivated"] == 4  # 3 not-seen + 1 age-stale
    call = fake_repo.not_seen_calls[0]
    assert call["source_platform"] == "ycombinator"
    assert "careers_url" not in call
    assert call["since_iso"] > (
        datetime.now(timezone.utc) - timedelta(minutes=5)
    ).isoformat()


@pytest.mark.asyncio
async def test_failed_crawl_deactivates_nothing(monkeypatch):
    fake_repo = _FakeRepo()
    crawl_jobs = _patch_ingestion(
        monkeypatch, fake_repo, "ingest_ycombinator_jobs", RuntimeError("YC down")
    )

    with pytest.raises(RuntimeError):
        await crawl_jobs.crawl_company_job({"job_id": "t"}, "ycombinator", "")

    assert fake_repo.not_seen_calls == []
    assert fake_repo.stale_calls == []


@pytest.mark.asyncio
async def test_firecrawl_reconciliation_scoped_to_careers_url(monkeypatch):
    fake_repo = _FakeRepo()
    crawl_jobs = _patch_ingestion(
        monkeypatch, fake_repo, "ingest_firecrawl_jobs",
        {"discovered": 4, "inserted": 1, "updated": 1, "unchanged": 2,
         "deduplicated": 0, "skipped": 0},
    )

    await crawl_jobs.crawl_company_job(
        {"job_id": "t"}, "firecrawl", "PostHog|https://posthog.com/careers"
    )

    assert fake_repo.not_seen_calls[0]["careers_url"] == "https://posthog.com/careers"



def test_run_once_skips_disabled_provider(monkeypatch):
    runner = ScheduledCrawlRunner()
    runner._enqueue_crawl = AsyncMock()
    _set_setting(monkeypatch, "firecrawl_enabled", False)

    results = _run(runner.run_once())

    assert all(not k.startswith("firecrawl:") for k in results)
    assert any(k.startswith("ycombinator") for k in results)


def test_run_once_respects_master_switch(monkeypatch):
    runner = ScheduledCrawlRunner()
    runner._enqueue_crawl = AsyncMock()
    _set_setting(monkeypatch, "job_crawl_enabled", False)

    assert _run(runner.run_once()) == {}
    runner._enqueue_crawl.assert_not_awaited()


def test_run_provider_pass_targets_only_that_provider():
    runner = ScheduledCrawlRunner()
    runner._enqueue_crawl = AsyncMock()

    results = _run(runner.run_provider_pass("yc"))

    assert results == {"ycombinator:": "enqueued"}
    runner._enqueue_crawl.assert_awaited_once_with("ycombinator", "")
