"""Tests for Phase 1 crawl observability data model, transitions, anomalies, and fallbacks."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository
from app.repositories.observability_repository import ObservabilityRepository
from app.workers.jobs.crawl_jobs import crawl_company_job


class MockExecuteResult:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class MockQueryBuilder:
    def __init__(self, data=None, count=None):
        self._data = data or []
        self._count = count

    def select(self, *args, **kwargs):
        return self

    def insert(self, *args, **kwargs):
        return self

    def update(self, *args, **kwargs):
        return self

    def delete(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def gte(self, *args, **kwargs):
        return self

    def lt(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        return MockExecuteResult(data=self._data, count=self._count)


def test_observability_repository_graceful_fallback_when_unavailable():
    """Verify probe-cache detects missing tables and degrades gracefully without crashing."""
    mock_client = MagicMock()
    mock_client.table.side_effect = Exception("relation crawl_runs does not exist")
    mock_client.supabase_url = "http://fake-supabase"

    repo = ObservabilityRepository(client=mock_client)
    assert repo.is_available() is False

    # Recording run returns None gracefully
    run_id = repo.record_crawl_run(
        source="ashby",
        slug="test-co",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        status="success",
    )
    assert run_id is None

    # Summary returns graceful disabled shape
    summary = repo.get_crawl_observability_summary()
    assert summary["available"] is False
    assert summary["anomalies_24h"] == []

    # Retention returns 0 pruned without error
    prune_res = repo.prune_old_observability_data()
    assert prune_res == {"pruned_events": 0, "pruned_runs": 0}


def test_observability_repository_records_runs_and_prunes_when_available():
    """Verify ObservabilityRepository correctly inserts and queries when tables exist."""
    mock_client = MagicMock()
    mock_client.supabase_url = "http://fake-supabase-avail"

    # Setup mock tables
    tables = {
        "crawl_runs": MockQueryBuilder(data=[{
            "id": "run-1", "source": "ashby", "slug": "test", "status": "anomaly",
            "started_at": "2026-10-06T10:00:00Z", "discovered": 0, "anomaly_reason": "dropped"
        }]),
        "job_events": MockQueryBuilder(data=[{"id": "ev-1"}]),
    }
    mock_client.table.side_effect = lambda t: tables.get(t, MockQueryBuilder())

    repo = ObservabilityRepository(client=mock_client)
    assert repo.is_available() is True

    # Insert crawl run
    run_id = repo.record_crawl_run(
        source="greenhouse",
        slug="stripe",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        status="success",
        discovered=42,
    )
    assert run_id is not None

    # Query summary
    summary = repo.get_crawl_observability_summary()
    assert summary["available"] is True
    assert len(summary["anomalies_24h"]) == 1

    # Prune
    prune_res = repo.prune_old_observability_data(retention_days=30, batch_size=100)
    assert prune_res["pruned_events"] == 1
    assert prune_res["pruned_runs"] == 1


def test_upsert_jobs_passes_crawl_run_id_with_legacy_fallback():
    """Verify JobRepository.upsert_jobs passes crawl_run_id to RPC and falls back if unsupported."""
    mock_client = MagicMock()
    mock_client.supabase_url = "http://fake-supabase-rpc"

    job = NormalizedJob(
        title="Software Engineer",
        company="Acme Corp",
        location="Remote",
        url="https://example.com/job/1",
        source="ashby",
        external_job_id="job-1",
        source_platform="ashby",
    )

    repo = JobRepository(client=mock_client)
    repo._has_rpc_batch = True
    repo._has_last_seen = True
    repo._has_mass_hiring = True

    # 1. Normal RPC with p_crawl_run_id
    mock_rpc = MagicMock()
    mock_rpc.execute.return_value = MockExecuteResult(data={"inserted": 1, "updated": 0, "unchanged": 0, "inserted_ids": ["job-1"]})
    mock_client.rpc.return_value = mock_rpc

    res = repo.upsert_jobs([job], source="ashby", slug="acme", crawl_run_id="test-run-uuid")
    assert res["inserted"] == 1
    call_args = mock_client.rpc.call_args
    assert call_args[0][0] == "upsert_jobs_batch"
    assert call_args[0][1]["p_crawl_run_id"] == "test-run-uuid"
    assert len(call_args[0][1]["jobs_json"]) == 1
    assert call_args[0][1]["jobs_json"][0]["title"] == "Software Engineer"

    # 2. Legacy RPC error fallback when p_crawl_run_id is not accepted
    calls = []
    def rpc_side_effect(name, params):
        calls.append((name, dict(params)))
        m = MagicMock()
        if "p_crawl_run_id" in params:
            m.execute.side_effect = Exception("function upsert_jobs_batch(jsonb, uuid) does not exist")
        else:
            m.execute.return_value = MockExecuteResult(data={"inserted": 1, "updated": 0, "unchanged": 0, "inserted_ids": ["job-1"]})
        return m

    mock_client.rpc.side_effect = rpc_side_effect
    res2 = repo.upsert_jobs([job], source="ashby", slug="acme", crawl_run_id="test-run-uuid")
    assert res2["inserted"] == 1
    # First tried with p_crawl_run_id, then retried without
    assert len(calls) == 2
    assert "p_crawl_run_id" in calls[0][1]
    assert "p_crawl_run_id" not in calls[1][1]


def test_deactivate_not_seen_since_passes_crawl_run_id_with_fallback():
    """Verify JobRepository.deactivate_not_seen_since passes crawl_run_id to RPC with fallback."""
    mock_client = MagicMock()
    mock_client.supabase_url = "http://fake-supabase-deact"

    repo = JobRepository(client=mock_client)
    repo._has_last_seen = True

    calls = []
    def rpc_side_effect(name, params):
        calls.append((name, dict(params)))
        m = MagicMock()
        if "p_crawl_run_id" in params:
            m.execute.side_effect = Exception("function deactivate_unseen_jobs_batch does not accept 7 arguments")
        else:
            m.execute.return_value = MockExecuteResult(data=3)
        return m

    mock_client.rpc.side_effect = rpc_side_effect
    # Populate probe cache so it knows RPC exists
    from app.repositories.job_repository import _PROBE_CACHE_MISS_RPC
    _PROBE_CACHE_MISS_RPC[repo._probe_key(mock_client)] = True

    count = repo.deactivate_not_seen_since(
        source_platform="ashby",
        since_iso="2026-10-06T10:00:00Z",
        slug="acme",
        crawl_run_id="run-uuid-deact",
    )
    assert count == 3
    assert len(calls) == 2
    assert "p_crawl_run_id" in calls[0][1]
    assert "p_crawl_run_id" not in calls[1][1]


@pytest.mark.asyncio
async def test_crawl_company_job_anomaly_detection_skips_deactivation_and_alerts():
    """Verify anomaly detection (<50% of previous active) flags anomaly, skips deactivation, and fires alert."""
    ctx = {"job_id": "job-test-anomaly"}

    mock_ingestion = MagicMock()
    mock_ingestion.ingest_ashby_jobs = AsyncMock(return_value={"discovered": 5, "inserted": 0, "updated": 5, "unchanged": 0})
    mock_ingestion.job_repository = MagicMock()

    # Previous active query returns 50 jobs (5 < 50 * 0.5 => anomaly)
    mock_prev_res = MockExecuteResult(count=50)
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_prev_res
    mock_ingestion.job_repository._client.table.return_value = mock_table

    mock_deact = MagicMock()
    mock_ingestion.job_repository.deactivate_not_seen_since = mock_deact

    with patch("app.workers.jobs.crawl_jobs.JobIngestionService", return_value=mock_ingestion), \
         patch("app.services.jobs.crawl_dispatcher.complete_target", new_callable=AsyncMock) as mock_complete, \
         patch("app.workers.jobs.crawl_jobs._record_crawl_status", new_callable=AsyncMock) as mock_record_redis, \
         patch("app.repositories.observability_repository.ObservabilityRepository.record_crawl_run") as mock_record_db, \
         patch("sentry_sdk.capture_message") as mock_sentry:

        result = await crawl_company_job(ctx, source="ashby", slug="acme")

        assert result["status"] == "anomaly"
        assert result["deactivated"] == 0
        mock_deact.assert_not_called()
        mock_sentry.assert_called_once()
        assert "Crawl anomaly detected" in mock_sentry.call_args[0][0]
