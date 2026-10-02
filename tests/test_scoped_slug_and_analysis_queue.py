"""Tests for:
1. crawl_target_slug scoping where company != slug.
2. Warning logging on unscoped deactivation.
3. _defer_by / _defer_until parameter integrity.
4. Periodic backfill of jobs missing intelligence via analyze_jobs_batch.
5. Analysis queue routing.
"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import get_settings
from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository
from app.workers.dispatcher import enqueue, enqueue_crawl_company
from app.workers.settings import AnalysisWorkerSettings, WorkerSettings
from app.services.jobs.crawl_dispatcher import backfill_missing_intelligence


class _FakeQuery:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data
        self.count = len(data)

    def select(self, *args: Any, **kwargs: Any) -> "_FakeQuery":
        return self

    def eq(self, field: str, value: Any) -> "_FakeQuery":
        return _FakeQuery([r for r in self.data if r.get(field) == value])

    def ilike(self, field: str, pattern: str) -> "_FakeQuery":
        clean = pattern.replace("%", "").lower()
        return _FakeQuery([r for r in self.data if clean in str(r.get(field, "")).lower()])

    def lt(self, field: str, value: Any) -> "_FakeQuery":
        return _FakeQuery([r for r in self.data if str(r.get(field, "")) < str(value)])

    def in_(self, field: str, values: list[Any]) -> "_FakeQuery":
        val_set = set(values)
        return _FakeQuery([r for r in self.data if r.get(field) in val_set])

    def order(self, *args: Any, **kwargs: Any) -> "_FakeQuery":
        return self

    def limit(self, limit: int) -> "_FakeQuery":
        return _FakeQuery(self.data[:limit])

    def execute(self) -> "_FakeQuery":
        return self


class _FakeClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "jobs": [],
            "job_intelligence": [],
        }
        self.rpcs: list[tuple[str, dict[str, Any]]] = []

    def table(self, name: str) -> Any:
        client_self = self

        class _TableHandler:
            def select(self, *args: Any, **kwargs: Any) -> _FakeQuery:
                return _FakeQuery(list(client_self.tables.get(name, [])))

            def update(self, payload: dict[str, Any], **kwargs: Any) -> Any:
                class _Updater:
                    def __init__(self, table_name: str) -> None:
                        self.table_name = table_name

                    def in_(self, field: str, values: list[Any]) -> "_Updater":
                        val_set = set(values)
                        for r in client_self.tables[self.table_name]:
                            if r.get(field) in val_set:
                                r.update(payload)
                        return self

                    def eq(self, field: str, value: Any) -> "_Updater":
                        for r in client_self.tables[self.table_name]:
                            if r.get(field) == value:
                                r.update(payload)
                        return self

                    def execute(self) -> MagicMock:
                        return MagicMock(data=[])

                return _Updater(name)

            def insert(self, payload: Any, **kwargs: Any) -> Any:
                rows = payload if isinstance(payload, list) else [payload]
                for r in rows:
                    row_copy = dict(r)
                    if "id" not in row_copy:
                        row_copy["id"] = f"gen-{len(client_self.tables[name])}"
                    client_self.tables[name].append(row_copy)
                return MagicMock(execute=lambda: MagicMock(data=rows))

        return _TableHandler()

    def rpc(self, name: str, params: dict[str, Any]) -> Any:
        self.rpcs.append((name, params))
        class _RpcMock:
            def execute(self) -> MagicMock:
                return MagicMock(data=1)
        return _RpcMock()


# ---------------------------------------------------------------------------
# 1. Company Name != Slug Scoping Test
# ---------------------------------------------------------------------------

def test_crawl_target_slug_set_at_upsert_and_scopes_deactivation_when_company_differs():
    """Verify that company != slug (e.g. company='Figma, Inc.', slug='figma')

    stores crawl_target_slug='figma', and legacy deactivation scopes strictly by
    crawl_target_slug, never accidentally matching or dropping based on company name.
    """
    client = _FakeClient()
    repo = JobRepository(client)
    repo._has_last_seen_at = True
    repo._has_rpc_batch = False

    job = NormalizedJob(
        title="Senior Software Engineer",
        company="Figma, Inc.",  # Official entity name != slug
        external_job_id="figma-101",
        source_platform="greenhouse",
        description="Great job",
    )

    # 1. Upsert with slug
    res = repo.upsert_jobs([job], source="greenhouse", slug="figma")
    assert res["discovered"] == 1

    stored_jobs = client.tables["jobs"]
    assert len(stored_jobs) == 1
    assert stored_jobs[0]["company"] == "Figma, Inc."
    assert stored_jobs[0]["crawl_target_slug"] == "figma"
    # Simulate that figma-101 was seen in a past crawl but missing in the latest crawl
    stored_jobs[0]["last_seen_at"] = "2020-01-01T00:00:00Z"

    # Add a job for a DIFFERENT slug but similar company name
    client.tables["jobs"].append({
        "id": "other-202",
        "external_job_id": "other-202",
        "source_platform": "greenhouse",
        "company": "Figma, Inc.",  # Same company name string!
        "crawl_target_slug": "figma-design-board",  # Different target slug!
        "is_active": True,
        "last_seen_at": "2020-01-01T00:00:00Z",
    })

    # 2. Deactivate not seen since now, scoped by slug="figma" (test legacy fallback path)
    from app.repositories.job_repository import _PROBE_CACHE_MISS_RPC
    _PROBE_CACHE_MISS_RPC[repo._probe_key(client)] = False

    now_iso = datetime.now(timezone.utc).isoformat()
    deactivated = repo.deactivate_not_seen_since(
        source_platform="greenhouse",
        since_iso=now_iso,
        slug="figma",
    )

    # Only the row matching crawl_target_slug="figma" is deactivated!
    figma_job = next(j for j in client.tables["jobs"] if j["external_job_id"] == "figma-101")
    other_job = next(j for j in client.tables["jobs"] if j["external_job_id"] == "other-202")

    assert figma_job["is_active"] is False
    assert other_job["is_active"] is True  # preserved, not touched by "figma" slug deactivation

    # 3. Also verify RPC path passes p_slug
    _PROBE_CACHE_MISS_RPC[repo._probe_key(client)] = True
    repo.deactivate_not_seen_since(
        source_platform="greenhouse",
        since_iso=now_iso,
        slug="figma",
    )
    rpc_name, rpc_params = client.rpcs[-1]
    assert rpc_name == "deactivate_unseen_jobs_batch"
    assert rpc_params["p_slug"] == "figma"


# ---------------------------------------------------------------------------
# 2. Unscoped Deactivation Warnings Test
# ---------------------------------------------------------------------------

def test_unscoped_deactivation_logs_warning_with_source_and_slug(caplog):
    """Verify that legacy-fallback path logs a warning with source and slug each time

    an unscoped deactivation is refused on a multi-company source.
    """
    client = _FakeClient()
    repo = JobRepository(client)
    repo._has_last_seen_at = True

    # 1. Stale deactivation refused
    with caplog.at_level("WARNING"):
        count = repo.deactivate_stale_jobs(source_platform="greenhouse", slug="stripe")
        # With slug provided, it's not refused
        assert count == 0

    caplog.clear()
    with caplog.at_level("WARNING"):
        # Without company, careers_url, or slug: REFUSED!
        count = repo.deactivate_stale_jobs(source_platform="greenhouse")
        assert count == 0
        assert any(
            "Refusing unscoped stale deactivation for multi-company source greenhouse" in r.message
            for r in caplog.records
        )

    caplog.clear()
    with caplog.at_level("WARNING"):
        # Not seen deactivation refused when RPC unavailable
        client_no_rpc = _FakeClient()
        client_no_rpc.rpc = MagicMock(side_effect=Exception("RPC unavailable"))
        repo_no_rpc = JobRepository(client_no_rpc)
        repo_no_rpc._has_last_seen_at = True

        count = repo_no_rpc.deactivate_not_seen_since(
            source_platform="ashby",
            since_iso="2026-01-01T00:00:00Z",
        )
        assert count == 0
        assert any(
            "Refusing unscoped not-seen deactivation for multi-company source ashby" in r.message
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# 3. Defer Parameter Grep & Functional Integrity Test
# ---------------------------------------------------------------------------

def test_grep_no_illegal_defer_parameters_in_app():
    """Verify git grep -n '_defer=\\|defer_until=' app/ returns zero hits."""
    result = subprocess.run(
        ["git", "grep", "-n", "_defer=\\|defer_until=", "app/"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 or not result.stdout.strip(), f"Found illegal defer occurrences: {result.stdout}"


@pytest.mark.asyncio
async def test_defer_by_and_defer_until_passed_to_redis():
    """Verify _defer_by and _defer_until are correctly passed to ARQ."""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test-job-id"))

    with patch("app.workers.dispatcher._get_redis", return_value=mock_redis):
        # 1. enqueue_crawl_company with _defer_by
        job_id = await enqueue_crawl_company("greenhouse", "figma", _defer_by=42)
        assert job_id == "test-job-id"
        _, kwargs = mock_redis.enqueue_job.call_args
        assert kwargs.get("_defer_by") == 42

        # 2. enqueue_crawl_company with _defer_until
        future_dt = datetime.now(timezone.utc) + timedelta(minutes=10)
        await enqueue_crawl_company("greenhouse", "figma", _defer_until=future_dt)
        _, kwargs = mock_redis.enqueue_job.call_args
        assert kwargs.get("_defer_until") == future_dt


# ---------------------------------------------------------------------------
# 4. Periodic Backfill Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_periodic_backfill_chunks_and_enqueues_missing_intelligence():
    """Verify active jobs missing intelligence fields are chunked and enqueued to analysis queue."""
    mock_redis = AsyncMock()
    mock_redis.enqueue_job = AsyncMock(return_value=MagicMock(job_id="analysis-backfill-id"))

    fake_client = MagicMock()
    # Mock RPC returning 2 unanalyzed jobs
    fake_client.rpc.return_value.execute.return_value.data = [
        {"id": "job-uuid-1", "external_job_id": "ext-1"},
        {"id": "job-uuid-2", "external_job_id": "ext-2"},
    ]

    with patch("app.workers.dispatcher._get_redis", return_value=mock_redis), \
         patch("app.services.jobs.crawl_dispatcher.get_service_client", return_value=fake_client), \
         patch("app.services.jobs.crawl_dispatcher._rpc", return_value=[
             {"id": "job-uuid-1", "external_job_id": "ext-1"},
             {"id": "job-uuid-2", "external_job_id": "ext-2"},
         ]):
        count = await backfill_missing_intelligence({})
        assert count == 2
        assert mock_redis.enqueue_job.called
        call_args = mock_redis.enqueue_job.call_args
        assert call_args[0][0] == "analyze_jobs_batch"
        assert "job-uuid-1" in call_args[0][1]
        assert call_args[1].get("_queue_name") == get_settings().analysis_queue_name


# ---------------------------------------------------------------------------
# 5. Analysis Queue Name Routing & Worker Configuration Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analysis_jobs_route_to_analysis_queue():
    """Verify analyze_job_intelligence and analyze_jobs_batch route to configured analysis queue."""
    mock_redis = AsyncMock()
    mock_redis.enqueue_job = AsyncMock(return_value=MagicMock(job_id="intel-job-id"))

    with patch("app.workers.dispatcher._get_redis", return_value=mock_redis):
        # Enqueue intelligence job via dispatcher
        await enqueue("analyze_job_intelligence", "test-job-id")
        _, kwargs = mock_redis.enqueue_job.call_args
        assert kwargs.get("_queue_name") == get_settings().analysis_queue_name


def test_analysis_worker_settings_configured():
    """Verify AnalysisWorkerSettings uses analysis_queue_name and includes analysis jobs."""
    settings = get_settings()
    assert AnalysisWorkerSettings.queue_name == settings.analysis_queue_name
    func_names = [f.name for f in AnalysisWorkerSettings.functions]
    assert "analyze_job_intelligence" in func_names
    assert "analyze_jobs_batch" in func_names
