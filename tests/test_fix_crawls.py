import pytest
import datetime
from unittest.mock import patch, MagicMock, AsyncMock
import threading
from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository
from app.workers.jobs.crawl_jobs import crawl_company_job
from app.db.supabase import PersistenceTimeoutError
from arq import Retry

@pytest.fixture
def mock_client():
    client = MagicMock()
    # default rpc mock
    rpc_mock = MagicMock()
    rpc_mock.execute.return_value = MagicMock(data={"inserted": 1, "updated": 0, "unchanged": 0})
    client.rpc.return_value = rpc_mock
    client.table.return_value = MagicMock()
    return client

@pytest.fixture
def repo(mock_client):
    repo = JobRepository(client=mock_client)
    repo.clear_probe_cache()
    # mock probe checks
    repo._probe_has_rpc_batch = MagicMock(return_value=True)
    repo._probe_has_last_seen_at = MagicMock(return_value=True)
    repo._probe_has_mass_hiring = MagicMock(return_value=False)
    repo._probe_has_provenance = MagicMock(return_value=True)
    return repo

def test_rpc_path_selection(repo, mock_client):
    jobs = [NormalizedJob(title="Engineer", company="Acme", source_platform="ashby", external_job_id="123")]
    res = repo.upsert_jobs(jobs, source="ashby", slug="acme")
    assert res["path"] == "rpc"
    mock_client.rpc.assert_called_with("upsert_jobs_batch", {"jobs_json": [jobs[0].to_db_row()]})

def test_legacy_fallback(repo, mock_client):
    repo._probe_has_rpc_batch.return_value = False
    mock_client.table().select().in_().execute.return_value = MagicMock(data=[])
    jobs = [NormalizedJob(title="Engineer", company="Acme", source_platform="ashby", external_job_id="123")]
    res = repo.upsert_jobs(jobs, source="ashby", slug="acme")
    assert res["path"] == "legacy"

def test_unchanged_hash_skip(repo, mock_client):
    jobs = [NormalizedJob(title="Engineer", company="Acme", source_platform="ashby", external_job_id="123")]
    
    # Mock history returned hash
    history_res = MagicMock()
    history_res.data = [{"content_hash": repo._compute_job_hash(jobs)}]
    mock_client.table().select().eq().eq().order().limit().execute.return_value = history_res
    
    res = repo.upsert_jobs(jobs, source="ashby", slug="acme")
    assert res["path"] == "unchanged"
    # RPC shouldn't be called for upsert if unchanged
    mock_client.rpc.assert_not_called()
    # Touch should be called
    mock_client.table().update.assert_called()

def test_chunking(repo, mock_client):
    import app.repositories.job_repository as jr
    old_chunk = jr._UPSERT_WRITE_CHUNK
    jr._UPSERT_WRITE_CHUNK = 2
    try:
        jobs = [
            NormalizedJob(title="Eng 1", company="Acme", source_platform="ashby", external_job_id="1"),
            NormalizedJob(title="Eng 2", company="Acme", source_platform="ashby", external_job_id="2"),
            NormalizedJob(title="Eng 3", company="Acme", source_platform="ashby", external_job_id="3"),
        ]
        repo.upsert_jobs(jobs, source="ashby", slug="acme")
        assert mock_client.rpc.call_count == 2
    finally:
        jr._UPSERT_WRITE_CHUNK = old_chunk

@pytest.mark.asyncio
async def test_retry_on_timeout_and_lock_release():
    ctx = {"job_id": "test_id", "job_try": 2}
    with patch("app.workers.jobs.crawl_jobs._dispatch_ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.side_effect = PersistenceTimeoutError("Timeout")
        with patch("app.workers.settings.get_redis_pool", new_callable=AsyncMock) as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.get.return_value = b"test_id"
            mock_get_redis.return_value = mock_redis
            
            with pytest.raises(Retry) as exc_info:
                await crawl_company_job(ctx, "ashby", "acme")
                
            assert exc_info.value.defer_score == 60 # 2 * 30
            mock_redis.delete.assert_called_with("crawl_lock:ashby:acme")

@pytest.mark.asyncio
async def test_stale_deactivation_guards():
    ctx = {"job_id": "test_id", "job_try": 1}
    with patch("app.workers.jobs.crawl_jobs._dispatch_ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = {"discovered": 0}
        
        with patch("app.workers.jobs.crawl_jobs.JobIngestionService") as mock_service:
            instance = mock_service.return_value
            # return 10 previous active
            mock_client = MagicMock()
            res = MagicMock()
            res.count = 10
            mock_client.table().select().eq().eq().execute.return_value = res
            instance.job_repository._client = mock_client
            
            res = await crawl_company_job(ctx, "ashby", "acme")
            assert res["status"] == "suspicious_empty"
            assert res["deactivated"] == 0

