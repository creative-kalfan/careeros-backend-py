"""Tests for scoped reconciliation, inserted_ids semantics, chunked analysis, and JobNotFound."""

import asyncio
from datetime import datetime, timezone
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository
from app.workers.jobs.job_intelligence_job import (
    analyze_job_intelligence_job,
    analyze_jobs_batch,
)
from app.workers.jobs.crawl_jobs import crawl_company_job


@pytest.fixture
def mock_client():
    client = MagicMock()
    rpc_mock = MagicMock()
    rpc_mock.execute.return_value = MagicMock(data=0)
    client.rpc.return_value = rpc_mock
    client.table.return_value = MagicMock()
    return client


@pytest.fixture
def repo(mock_client):
    r = JobRepository(client=mock_client)
    r.clear_probe_cache()
    r._probe_has_rpc_batch = MagicMock(return_value=True)
    r._probe_has_last_seen_at = MagicMock(return_value=True)
    r._probe_has_mass_hiring = MagicMock(return_value=False)
    r._probe_has_provenance = MagicMock(return_value=True)
    return r


# -----------------------------------------------------------------------------
# 1. Scoping Bug: Two companies under one source
# -----------------------------------------------------------------------------

def test_scoped_reconciliation_rpc_carries_company_and_careers_url(repo, mock_client):
    """Crawl of Company A on firecrawl must only reconcile Company A, leaving Company B untouched."""
    now_iso = datetime.now(timezone.utc).isoformat()
    mock_client.rpc.return_value.execute.return_value = MagicMock(data=3)

    repo.deactivate_not_seen_since(
        source_platform="firecrawl",
        since_iso=now_iso,
        company="Company A",
        careers_url="https://company-a.com/careers",
        miss_threshold=2,
    )

    # RPC must receive company and careers_url
    mock_client.rpc.assert_called_with(
        "deactivate_unseen_jobs_batch",
        {
            "p_source": "firecrawl",
            "p_company": "Company A",
            "p_careers_url": "https://company-a.com/careers",
            "p_since": now_iso,
            "p_threshold": 2,
        },
    )


def test_scoped_reconciliation_legacy_filters_by_company_and_url(repo, mock_client):
    """Legacy query path must filter by company and careers_url with case-insensitivity."""
    now_iso = datetime.now(timezone.utc).isoformat()
    # Force RPC unavailable
    with patch.dict("app.repositories.job_repository._PROBE_CACHE_MISS_RPC", {repo._probe_key(mock_client): False}):
        query_mock = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.lt.return_value = query_mock
        query_mock.eq.return_value = query_mock
        query_mock.ilike.return_value = query_mock
        query_mock.execute.return_value = MagicMock(data=[{"id": "job_1"}])

        repo.deactivate_not_seen_since(
            source_platform="firecrawl",
            since_iso=now_iso,
            company="Company A",
            careers_url="https://company-a.com/careers",
        )

        # Must filter specifically by careers_url and ilike company
        query_mock.eq.assert_any_call("careers_url", "https://company-a.com/careers")
        query_mock.ilike.assert_any_call("company", "Company A")


def test_unscoped_multi_company_reconciliation_refused(repo, mock_client):
    """Attempting unscoped deactivation on multi-company sources like firecrawl or ashby must be refused."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with patch.dict("app.repositories.job_repository._PROBE_CACHE_MISS_RPC", {repo._probe_key(mock_client): False}):
        count = repo.deactivate_not_seen_since(
            source_platform="firecrawl",
            since_iso=now_iso,
            company=None,
            careers_url=None,
        )
        assert count == 0
        mock_client.table.assert_not_called()

        count_stale = repo.deactivate_stale_jobs(
            source_platform="ashby",
            company=None,
            careers_url=None,
        )
        assert count_stale == 0


# -----------------------------------------------------------------------------
# 2. inserted_ids semantics: second crawl of unchanged board returns 0 inserted
# -----------------------------------------------------------------------------

def test_unchanged_board_crawl_returns_zero_inserted_ids(repo, mock_client):
    """A second crawl of an unchanged board must return 0 inserted count and empty inserted_ids."""
    mock_client.rpc.return_value.execute.return_value = MagicMock(
        data={
            "inserted": 0,
            "updated": 0,
            "unchanged": 10,
            "inserted_ids": [],
        }
    )

    jobs = [
        NormalizedJob(
            title=f"Engineer {i}",
            company="Acme Corp",
            source_platform="greenhouse",
            external_job_id=f"job_{i}",
        )
        for i in range(10)
    ]

    result = repo.upsert_jobs(jobs, source="greenhouse", slug="acme")

    assert result["inserted"] == 0
    assert result["unchanged"] == 10
    assert repo.last_inserted_ids == []


# -----------------------------------------------------------------------------
# 3. Chunked analysis batch enqueue
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_crawl_job_enqueues_chunked_analysis_batches(monkeypatch):
    """Crawl discovering 55 new jobs enqueues batches of 25 with jitter, not 55 individual jobs."""
    enqueued_jobs = []

    mock_redis = MagicMock()
    async def _mock_enqueue(job_name, *args, **kwargs):
        enqueued_jobs.append((job_name, args, kwargs))
        return MagicMock(job_id="mock_job_id")

    mock_redis.enqueue_job = _mock_enqueue
    mock_redis.zcard = AsyncMock(return_value=0)

    from app.workers import settings
    monkeypatch.setattr(settings, "get_redis_pool", AsyncMock(return_value=mock_redis))
    import app.workers.dispatcher as disp_mod
    monkeypatch.setattr(disp_mod, "_get_redis", AsyncMock(return_value=mock_redis))



    # Mock crawl dependencies
    import app.workers.jobs.crawl_jobs as crawl_mod
    monkeypatch.setattr(crawl_mod, "_uses_complete_inventory", lambda s: True)
    monkeypatch.setattr(crawl_mod, "_india_only_for", lambda s, slug: False)
    monkeypatch.setattr(crawl_mod, "_record_crawl_status", AsyncMock())

    from app.services.jobs import crawl_dispatcher
    monkeypatch.setattr(crawl_dispatcher, "complete_target", AsyncMock())

    # Mock crawler discovering 55 jobs
    mock_crawler = MagicMock()
    mock_crawler.crawl = AsyncMock(return_value=[
        NormalizedJob(title=f"Job {i}", company="Acme", source_platform="lever", external_job_id=f"ext_{i}")
        for i in range(55)
    ])
    mock_crawler.enrich = None

    mock_ingestion = MagicMock()
    mock_ingestion.crawler_factory = MagicMock(return_value=mock_crawler)
    mock_ingestion.normalize_and_filter = MagicMock(side_effect=lambda jobs: (jobs, 0))
    mock_ingestion.ingest_lever_jobs = AsyncMock(return_value={
        "discovered": 55, "inserted": 55, "updated": 0, "unchanged": 0, "deduplicated": 0, "skipped": 0,
    })
    mock_ingestion.job_repository.upsert_jobs.return_value = {
        "discovered": 55, "inserted": 55, "updated": 0, "unchanged": 0, "deduplicated": 0, "skipped": 0,
    }
    inserted_ids_list = [f"ext_{i}" for i in range(55)]
    mock_ingestion.job_repository.last_inserted_ids = inserted_ids_list
    mock_ingestion.job_repository.last_analysis_ids = inserted_ids_list
    mock_ingestion.job_repository._client.table().select().eq().eq().execute.return_value = MagicMock(count=0)

    monkeypatch.setattr(crawl_mod, "JobIngestionService", MagicMock(return_value=mock_ingestion))
    monkeypatch.setattr(crawl_mod, "_deactivate_after_success", lambda *args, **kwargs: (0, 0, 0, 0))

    res = await crawl_company_job({}, "lever", "acme")
    assert res["status"] == "success"

    # Verify enqueue calls: 55 jobs / 25 chunk_size = 3 chunks (25, 25, 5)
    batch_calls = [c for c in enqueued_jobs if c[0] == "analyze_jobs_batch"]
    assert len(batch_calls) == 3
    assert len(batch_calls[0][1][0]) == 25
    assert len(batch_calls[1][1][0]) == 25
    assert len(batch_calls[2][1][0]) == 5

    # Verify jitter deferral
    for c in batch_calls:
        assert "_defer_by" in c[2]
        assert c[2]["_defer_by"] >= 1


# -----------------------------------------------------------------------------
# 4. JobNotFound: Info log, no failed status, accurate diagnosis
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_not_found_logs_info_and_returns_status(monkeypatch, caplog):
    """JobNotFound must log INFO, return status='job_not_found', and report diagnosis cause."""
    mock_repo = MagicMock()
    mock_repo.get_job.return_value = None
    mock_repo.diagnose_job_missing.return_value = "inactive"

    with patch("app.workers.jobs.job_intelligence_job.JobRepository", return_value=mock_repo):
        with caplog.at_level(logging.INFO):
            result = await analyze_job_intelligence_job(
                {"job_id": "test_analysis_1", "job_try": 1, "score": 1000},
                job_id="missing_job_123",
            )

    assert result["success"] is False
    assert result["status"] == "job_not_found"
    assert result["cause"] == "inactive"

    # Verify no ERROR or FAILED logs
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)
    # Verify INFO log
    info_records = [r for r in caplog.records if "status=job_not_found cause=inactive" in r.getMessage()]
    assert len(info_records) == 1


@pytest.mark.asyncio
async def test_analyze_jobs_batch_handles_missing_jobs_gracefully(monkeypatch):
    """analyze_jobs_batch aggregates not_found counts and causes without raising."""
    mock_repo = MagicMock()
    mock_repo.get_job.side_effect = lambda jid: {"id": jid, "title": "Eng", "company": "Co"} if jid == "found" else None
    mock_repo.diagnose_job_missing.return_value = "missing"

    mock_intel_repo = MagicMock()
    mock_service = MagicMock()
    mock_service.analyze_job.return_value = MagicMock(skills=[], requirements=[], keywords=[])

    with patch("app.workers.jobs.job_intelligence_job.JobRepository", return_value=mock_repo), \
         patch("app.workers.jobs.job_intelligence_job.JobIntelligenceRepository", return_value=mock_intel_repo), \
         patch("app.workers.jobs.job_intelligence_job.JobIntelligenceService", return_value=mock_service):

        res = await analyze_jobs_batch(
            {"job_id": "batch_1", "job_try": 1},
            job_ids=["found", "not_found_1", "not_found_2"],
        )

    assert res["success"] is True
    assert res["total"] == 3
    assert res["succeeded"] == 1
    assert res["not_found"] == 2
    assert res["causes"] == {"missing": 2}


# -----------------------------------------------------------------------------
# 5. Firecrawl interval floor
# -----------------------------------------------------------------------------

def test_firecrawl_interval_floor():
    """Firecrawl targets must enforce adaptive floor of at least 72h (4320 mins)."""
    from app.services.jobs.crawl_dispatcher import adaptive_interval_minutes
    from app.config import get_settings

    settings = get_settings()
    firecrawl_floor_minutes = int(settings.firecrawl_min_interval_hours * 60)
    assert firecrawl_floor_minutes >= 4320

    # Even if changed is True, interval cannot drop below minimum floor
    interval = adaptive_interval_minutes(
        1000,
        changed=True,
        unchanged_streak=0,
        priority=1,
        minimum=firecrawl_floor_minutes,
        maximum=settings.crawl_max_interval_minutes,
    )
    assert interval >= 4320

@pytest.mark.asyncio
async def test_crawl_job_skips_enqueue_when_no_content_hash_changed(monkeypatch):
    """Crawl discovering jobs but with unchanged content hashes should not enqueue to analysis."""
    enqueued_jobs = []
    
    mock_redis = MagicMock()
    async def _mock_enqueue(job_name, *args, **kwargs):
        enqueued_jobs.append((job_name, args, kwargs))
        
    mock_redis.enqueue_job = _mock_enqueue
    
    from app.workers import settings
    monkeypatch.setattr(settings, "get_redis_pool", AsyncMock(return_value=mock_redis))
    
    import app.workers.jobs.crawl_jobs as crawl_mod
    monkeypatch.setattr(crawl_mod, "_uses_complete_inventory", lambda s: True)
    monkeypatch.setattr(crawl_mod, "_india_only_for", lambda s, slug: False)
    monkeypatch.setattr(crawl_mod, "_record_crawl_status", AsyncMock())
    
    from app.services.jobs import crawl_dispatcher
    monkeypatch.setattr(crawl_dispatcher, "complete_target", AsyncMock())
    
    mock_crawler = MagicMock()
    mock_crawler.crawl = AsyncMock(return_value=[
        NormalizedJob(title="Job 1", company="Acme", source_platform="lever", external_job_id="ext_1")
    ])
    mock_crawler.enrich = None
    
    mock_ingestion = MagicMock()
    mock_ingestion.crawler_factory = MagicMock(return_value=mock_crawler)
    mock_ingestion.normalize_and_filter = MagicMock(side_effect=lambda jobs: (jobs, 0))
    mock_ingestion.ingest_lever_jobs = AsyncMock(return_value={
        "discovered": 1, "inserted": 0, "updated": 1, "unchanged": 0, "deduplicated": 0, "skipped": 0,
    })
    
    # Simulate upsert where the job was updated but content hash didn't change (analysis_ids is empty)
    mock_ingestion.job_repository.upsert_jobs.return_value = {
        "discovered": 1, "inserted": 0, "updated": 1, "unchanged": 0, "deduplicated": 0, "skipped": 0,
    }
    mock_ingestion.job_repository.last_inserted_ids = []
    mock_ingestion.job_repository.last_analysis_ids = []
    
    monkeypatch.setattr(crawl_mod, "JobIngestionService", MagicMock(return_value=mock_ingestion))
    monkeypatch.setattr(crawl_mod, "_deactivate_after_success", lambda *args, **kwargs: (0, 0, 0, 0))
    
    res = await crawl_company_job({}, "lever", "acme")
    assert res["status"] == "success"
    
    # Verify no enqueue calls for analysis batches were made
    batch_calls = [c for c in enqueued_jobs if c[0] == "analyze_jobs_batch"]
    assert len(batch_calls) == 0
