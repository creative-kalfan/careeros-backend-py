import asyncio
import datetime
import os
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from arq import Retry

from app.db.supabase import PersistenceTimeoutError
from app.crawlers.models import CrawledJob
from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository
from app.services.jobs.job_ingestion_service import JobIngestionService
from app.workers.jobs.crawl_jobs import crawl_company_job


@pytest.fixture
def mock_client():
    client = MagicMock()
    rpc_mock = MagicMock()
    rpc_mock.execute.return_value = MagicMock(data={"inserted": 1, "updated": 0, "unchanged": 0})
    client.rpc.return_value = rpc_mock
    client.table.return_value = MagicMock()
    return client


@pytest.fixture
def repo(mock_client):
    repo = JobRepository(client=mock_client)
    repo.clear_probe_cache()
    repo._probe_has_rpc_batch = MagicMock(return_value=True)
    repo._probe_has_last_seen_at = MagicMock(return_value=True)
    repo._probe_has_mass_hiring = MagicMock(return_value=False)
    repo._probe_has_provenance = MagicMock(return_value=True)
    return repo


# -----------------------------------------------------------------------------
# 1. RPC path vs Legacy fallback selection
# -----------------------------------------------------------------------------

def test_rpc_path_selection(repo, mock_client):
    jobs = [NormalizedJob(title="Engineer", company="Acme", source_platform="ashby", external_job_id="123")]
    res = repo.upsert_jobs(jobs, source="ashby", slug="acme")
    assert repo.last_path == "rpc"
    assert mock_client.rpc.call_count == 1
    call_args = mock_client.rpc.call_args
    assert call_args[0][0] == "upsert_jobs_batch"
    assert len(call_args[0][1]["jobs_json"]) == 1
    assert call_args[0][1]["jobs_json"][0]["title"] == "Engineer"


def test_legacy_fallback_selection(repo, mock_client):
    repo._probe_has_rpc_batch.return_value = False
    mock_client.table().select().eq().in_().execute.return_value = MagicMock(data=[])
    jobs = [NormalizedJob(title="Engineer", company="Acme", source_platform="ashby", external_job_id="123")]
    res = repo.upsert_jobs(jobs, source="ashby", slug="acme")
    assert repo.last_path == "legacy"
    mock_client.rpc.assert_not_called()
    assert mock_client.table().insert.called or mock_client.table().update.called


# -----------------------------------------------------------------------------
# 2. Chunking
# -----------------------------------------------------------------------------

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
        res = repo.upsert_jobs(jobs, source="ashby", slug="acme")
        assert repo.last_path == "rpc"
        assert mock_client.rpc.call_count == 2
    finally:
        jr._UPSERT_WRITE_CHUNK = old_chunk


# -----------------------------------------------------------------------------
# 3. posted_at coalesce semantics
# -----------------------------------------------------------------------------

def test_posted_at_coalesce_existing_kept_when_incoming_has_different_date(repo):
    """Existing non-null posted_at is never overwritten on recrawl."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    existing = {
        "id": "job-uuid-1",
        "external_job_id": "job-1",
        "source_platform": "ashby",
        "title": "Engineer",
        "posted_at": "2026-01-01T00:00:00+00:00",
        "is_active": True,
    }
    incoming_row = {
        "external_job_id": "job-1",
        "source_platform": "ashby",
        "title": "Engineer (Updated Title)",
        "posted_at": "2026-09-30T00:00:00+00:00",
        "is_active": True,
    }
    action, row_id, new_row = repo._classify_row(
        ("job-1", "ashby"), incoming_row, existing, now_iso, has_last_seen=True
    )
    assert action == "update"
    assert row_id == "job-uuid-1"
    # Preserves the earlier/original posted_at, not overwritten by new one
    assert new_row["posted_at"] == "2026-01-01T00:00:00+00:00"


def test_posted_at_null_never_fabricated():
    """NULL posted_at remains None and is never fabricated from created_at/last_seen_at."""
    crawled = CrawledJob(
        external_id="ext-1",
        title="Software Engineer",
        company="Acme",
        location="Remote",
        apply_url="https://example.com/jobs/1",
        description="Write code",
        source="ashby",
        posted_at=None,
    )
    from app.services.jobs.job_service import JobService
    service = JobService()
    norm = service.normalize_and_classify(crawled)
    assert norm.posted_at is None

    row = norm.to_db_row()
    assert row.get("posted_at") is None


def test_posted_at_coalesce_incoming_used_when_existing_is_null(repo):
    """When existing row has null posted_at, incoming posted_at is accepted."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    existing = {
        "id": "job-uuid-2",
        "external_job_id": "job-2",
        "source_platform": "ashby",
        "title": "Engineer",
        "posted_at": None,
        "is_active": True,
    }
    incoming_row = {
        "external_job_id": "job-2",
        "source_platform": "ashby",
        "title": "Engineer",
        "posted_at": "2026-09-15T00:00:00+00:00",
        "is_active": True,
    }
    action, row_id, new_row = repo._classify_row(
        ("job-2", "ashby"), incoming_row, existing, now_iso, has_last_seen=True
    )
    assert action == "update"
    assert new_row["posted_at"] == "2026-09-15T00:00:00+00:00"


# -----------------------------------------------------------------------------
# 4. Unchanged-hash skip
# -----------------------------------------------------------------------------

def test_unchanged_hash_skip(repo, mock_client):
    jobs = [NormalizedJob(title="Engineer", company="Acme", source_platform="ashby", external_job_id="123")]
    history_res = MagicMock()
    history_res.data = [{"content_hash": repo._compute_job_hash(jobs)}]
    mock_client.table().select().eq().eq().order().limit().execute.return_value = history_res

    res = repo.upsert_jobs(jobs, source="ashby", slug="acme")
    assert repo.last_path == "unchanged"
    mock_client.rpc.assert_not_called()
    mock_client.table().update.assert_called()


def test_unchanged_hash_bypass_with_env(repo, mock_client, monkeypatch):
    jobs = [NormalizedJob(title="Engineer", company="Acme", source_platform="ashby", external_job_id="123")]
    history_res = MagicMock()
    history_res.data = [{"content_hash": repo._compute_job_hash(jobs)}]
    mock_client.table().select().eq().eq().order().limit().execute.return_value = history_res

    monkeypatch.setenv("CRAWL_FORCE_FULL_PERSIST", "1")
    res = repo.upsert_jobs(jobs, source="ashby", slug="acme")
    assert repo.last_path == "rpc"
    assert mock_client.rpc.call_count == 1


# -----------------------------------------------------------------------------
# 5. Stale deactivation guards
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stale_deactivation_guard_zero_discovered():
    """Guard: Discovered 0 jobs when company had previously active jobs -> skip deactivation."""
    ctx = {"job_id": "test_id_1", "job_try": 1}
    with patch("app.workers.jobs.crawl_jobs._dispatch_ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = {"discovered": 0}
        with patch("app.workers.jobs.crawl_jobs.JobIngestionService") as mock_service:
            instance = mock_service.return_value
            mock_client = MagicMock()
            res = MagicMock()
            res.count = 25  # previously 25 active jobs
            q = mock_client.table().select().eq().eq()
            q.execute.return_value = res
            q.ilike.return_value.execute.return_value = res
            instance.job_repository._client = mock_client

            res_job = await crawl_company_job(ctx, "ashby", "acme")
            assert res_job["status"] == "suspicious_empty"
            assert res_job["deactivated"] == 0


@pytest.mark.asyncio
async def test_stale_deactivation_guard_partial_drop():
    """Guard: Discovered < 50% of previously active jobs (>10) -> skip deactivation."""
    ctx = {"job_id": "test_id_2", "job_try": 1}
    with patch("app.workers.jobs.crawl_jobs._dispatch_ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = {"discovered": 8}  # 8 is < 50% of 20
        with patch("app.workers.jobs.crawl_jobs.JobIngestionService") as mock_service:
            instance = mock_service.return_value
            mock_client = MagicMock()
            res = MagicMock()
            res.count = 20
            q = mock_client.table().select().eq().eq()
            q.execute.return_value = res
            q.ilike.return_value.execute.return_value = res
            instance.job_repository._client = mock_client

            res_job = await crawl_company_job(ctx, "ashby", "acme")
            assert res_job["status"] in ("anomaly", "suspicious_empty")
            assert res_job["deactivated"] == 0


@pytest.mark.asyncio
async def test_stale_deactivation_normal_flow():
    """Normal case: Discovered count plausible -> deactivation executes."""
    ctx = {"job_id": "test_id_3", "job_try": 1}
    with patch("app.workers.jobs.crawl_jobs._dispatch_ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = {"discovered": 18}  # 18 of 20 is > 50%
        with patch("app.workers.jobs.crawl_jobs.JobIngestionService") as mock_service:
            instance = mock_service.return_value
            mock_client = MagicMock()
            res = MagicMock()
            res.count = 20
            mock_client.table().select().eq().eq().execute.return_value = res
            instance.job_repository._client = mock_client

            with patch("app.workers.jobs.crawl_jobs._deactivate_after_success", return_value=(2, 1, 10, 10)):
                res_job = await crawl_company_job(ctx, "ashby", "acme")
                assert res_job["status"] == "success"
                assert res_job["deactivated"] == 3


# -----------------------------------------------------------------------------
# 6. Retry on timeout + Lock release in finally
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_on_timeout_and_lock_release():
    ctx = {"job_id": "test_job_retry", "job_try": 2}
    with patch("app.workers.jobs.crawl_jobs._dispatch_ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.side_effect = PersistenceTimeoutError("Timeout waiting for persistence")
        with patch("app.workers.settings.get_redis_pool", new_callable=AsyncMock) as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.get.return_value = b"test_job_retry"
            mock_get_redis.return_value = mock_redis

            with pytest.raises(Retry) as exc_info:
                await crawl_company_job(ctx, "ashby", "acme")

            # defer = job_try (2) * 30 = 60s -> 60000ms
            assert exc_info.value.defer_score == 60 * 1000
            mock_redis.delete.assert_called_with("crawl_lock:ashby:acme")


# -----------------------------------------------------------------------------
# 7. Concurrent ingests with different slugs (no shared mutable state)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_ingests_distinct_slugs():
    """Two concurrent ingests with different slugs persist only their own slug."""
    service = JobIngestionService()
    persisted_calls: list[dict] = []

    async def fake_persist(normalized_jobs, source=None, slug=None, cancel_event=None, **kwargs):
        await asyncio.sleep(0.01)
        persisted_calls.append({
            "source": source,
            "slug": slug,
            "titles": [j.title for j in normalized_jobs],
        })
        return {"discovered": len(normalized_jobs), "inserted": len(normalized_jobs), "path": "rpc"}

    service._persist_offloop = fake_persist

    job_a = CrawledJob(
        external_id="id-a",
        title="Engineer at Alpha",
        company="AlphaCorp",
        location="Remote",
        apply_url="https://alpha.example.com",
        description="alpha description",
        source="ashby",
    )
    job_b = CrawledJob(
        external_id="id-b",
        title="Designer at Beta",
        company="BetaCorp",
        location="Remote",
        apply_url="https://beta.example.com",
        description="beta description",
        source="ashby",
    )

    with patch("app.services.jobs.job_ingestion_service.AshbyAdapter") as mock_adapter_cls:
        def get_adapter(slug):
            mock = MagicMock()
            if slug == "alpha":
                mock.discover_jobs = AsyncMock(return_value=[job_a])
            else:
                mock.discover_jobs = AsyncMock(return_value=[job_b])
            return mock

        mock_adapter_cls.side_effect = get_adapter

        # Run concurrently on the same service instance
        res_a, res_b = await asyncio.gather(
            service.ingest_ashby_jobs("alpha"),
            service.ingest_ashby_jobs("beta"),
        )

        assert res_a["inserted"] == 1
        assert res_b["inserted"] == 1
        assert len(persisted_calls) == 2

        alpha_call = next(c for c in persisted_calls if c["slug"] == "alpha")
        beta_call = next(c for c in persisted_calls if c["slug"] == "beta")

        assert alpha_call["source"] == "ashby"
        assert alpha_call["titles"] == ["Engineer at Alpha"]

        assert beta_call["source"] == "ashby"
        assert beta_call["titles"] == ["Designer at Beta"]

        service.job_repository = MagicMock()
        deactivation_calls: list[dict] = []
        service.job_repository.deactivate_not_seen_since.side_effect = (
            lambda **kwargs: deactivation_calls.append(kwargs) or 0
        )
        service.job_repository.deactivate_stale_jobs.return_value = 0

        from app.workers.jobs.crawl_jobs import _deactivate_after_success

        await asyncio.gather(
            asyncio.to_thread(
                _deactivate_after_success, service, "firecrawl",
                "Alpha|https://alpha.example.com/careers", "2026-10-01T00:00:00+00:00", 30,
            ),
            asyncio.to_thread(
                _deactivate_after_success, service, "firecrawl",
                "Beta|https://beta.example.com/careers", "2026-10-01T00:00:00+00:00", 30,
            ),
        )
        assert {(call["company"], call["careers_url"]) for call in deactivation_calls} == {
            ("Alpha", "https://alpha.example.com/careers"),
            ("Beta", "https://beta.example.com/careers"),
        }
