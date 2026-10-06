"""Production hardening tests for CareerOS background jobs and queues.

Validates:
1. Workload isolation and centralized WorkloadClass enum.
2. Queue routing based on WorkloadClass.
3. Payload size safety limits.
4. Change-driven job intelligence (unchanged crawl -> 0 analysis jobs).
5. Analysis queue backlog protection and backpressure.
6. Worker memory soft threshold guard.
7. Health liveness and cached readiness endpoints.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.config import get_settings
from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository
from app.workers.dispatcher import enqueue
from app.workers.registry import WorkloadClass, get_job_definition, get_registered_jobs


def test_all_registered_jobs_have_valid_workload_class() -> None:
    jobs = get_registered_jobs()
    assert len(jobs) >= 8
    valid_classes = set(WorkloadClass)
    for job in jobs:
        assert job.workload_class in valid_classes, f"Job {job.name} has invalid class {job.workload_class}"

    # Specific workload verifications
    assert get_job_definition("crawl_company_job").workload_class == WorkloadClass.CRAWL
    assert get_job_definition("analyze_job_intelligence").workload_class == WorkloadClass.ANALYSIS
    assert get_job_definition("analyze_jobs_batch").workload_class == WorkloadClass.ANALYSIS
    assert get_job_definition("parse_resume_job").workload_class == WorkloadClass.CRITICAL_USER
    assert get_job_definition("generate_interview_prep_job").workload_class == WorkloadClass.CRITICAL_USER
    assert get_job_definition("embed_jobs_batch").workload_class == WorkloadClass.EMBEDDING
    assert get_job_definition("backfill_job_embeddings").workload_class == WorkloadClass.MAINTENANCE
    assert get_job_definition("prune_crawl_observability_job").workload_class == WorkloadClass.MAINTENANCE


@pytest.mark.asyncio
async def test_dispatcher_routes_analysis_jobs_to_analysis_queue() -> None:
    settings = get_settings()
    mock_redis = AsyncMock()
    mock_redis.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test-job-123"))

    with patch("app.workers.dispatcher._get_redis", return_value=mock_redis):
        job_id = await enqueue("analyze_jobs_batch", ["job-1", "job-2"])
        assert job_id == "test-job-123"
        call_kwargs = mock_redis.enqueue_job.call_args.kwargs
        assert call_kwargs.get("_queue_name") == settings.analysis_queue_name


@pytest.mark.asyncio
async def test_dispatcher_rejects_oversized_payload() -> None:
    settings = get_settings()
    # Create payload exceeding max_job_payload_bytes
    oversized_data = "x" * (settings.max_job_payload_bytes + 1024)

    with pytest.raises(ValueError, match="exceeds maximum allowed"):
        await enqueue("analyze_job_intelligence", oversized_data)


def test_change_driven_job_intelligence_filters_unchanged_jobs() -> None:
    """Verifies that timestamp or non-content touches do NOT trigger analysis."""
    repo = JobRepository(client=MagicMock())
    existing_row = {
        "id": "uuid-1",
        "external_job_id": "ext-1",
        "source_platform": "greenhouse",
        "title": "Software Engineer",
        "company": "TechCorp",
        "location": "Bengaluru",
        "description": "Build scalable systems.",
        "skills": ["python", "fastapi"],
        "posted_at": "2026-03-01T00:00:00Z",
        "last_seen_at": "2026-03-01T00:00:00Z",
        "is_active": True,
    }

    # 1. No change
    same_row = dict(existing_row)
    assert not repo._has_analysis_content_changed(existing_row, same_row)

    # 2. Only last_seen_at updated (timestamp touch)
    touch_row = dict(existing_row)
    touch_row["last_seen_at"] = "2026-03-05T00:00:00Z"
    assert not repo._has_analysis_content_changed(existing_row, touch_row)

    # 3. Meaningful change (description updated)
    changed_desc_row = dict(existing_row)
    changed_desc_row["description"] = "Build distributed scalable systems."
    assert repo._has_analysis_content_changed(existing_row, changed_desc_row)

    # 4. Meaningful change (skills updated)
    changed_skills_row = dict(existing_row)
    changed_skills_row["skills"] = ["python", "fastapi", "redis"]
    assert repo._has_analysis_content_changed(existing_row, changed_skills_row)


@pytest.mark.asyncio
async def test_crawl_job_respects_analysis_backlog_threshold() -> None:
    """When analysis queue depth exceeds threshold, skip immediate enqueue and defer."""
    from app.workers.jobs.crawl_jobs import crawl_company_job

    mock_redis = AsyncMock()
    # Mock analysis queue depth above threshold (e.g. 150 >= 100)
    mock_redis.zcard = AsyncMock(return_value=150)
    mock_redis.enqueue_job = AsyncMock()

    mock_ingestion = MagicMock()
    mock_ingestion.job_repository.last_analysis_ids = ["job-1", "job-2", "job-3"]
    mock_ingestion.ingest_greenhouse_jobs = AsyncMock(return_value={
        "discovered": 3,
        "inserted": 3,
        "updated": 0,
        "unchanged": 0,
    })

    with patch("app.workers.jobs.crawl_jobs.JobIngestionService", return_value=mock_ingestion), \
         patch("app.workers.dispatcher._get_redis", return_value=mock_redis), \
         patch("app.events.get_event_bus") as mock_bus:
        mock_bus.return_value.publish = AsyncMock()

        ctx = {"job_id": "crawl-test"}
        res = await crawl_company_job(ctx, "greenhouse", "stripe")
        assert res["status"] == "success"


        # Verify no analyze_jobs_batch was enqueued because depth was over threshold
        calls = [c for c in mock_redis.enqueue_job.call_args_list if c.args and c.args[0] == "analyze_jobs_batch"]
        assert len(calls) == 0


@pytest.mark.asyncio
async def test_dispatch_due_targets_respects_memory_soft_limit() -> None:
    from app.services.jobs.crawl_dispatcher import dispatch_due_targets

    with patch("app.services.jobs.crawl_dispatcher._migration_probe", return_value=True), \
         patch("psutil.Process") as mock_proc:
        # Mock 500MB RSS (> 420MB soft limit)
        mock_mem = MagicMock()
        mock_mem.rss = 500.0 * 1024.0 * 1024.0
        mock_proc.return_value.memory_info.return_value = mock_mem

        ctx = {}
        claimed = await dispatch_due_targets(ctx)
        assert claimed == 0


@pytest.mark.asyncio
async def test_health_live_and_ready_endpoints() -> None:
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. /health and /health/live
        res_live = await client.get("/health/live")
        assert res_live.status_code == 200
        assert res_live.json() == {"status": "ok"}

        # 2. /health/ready
        with patch("app.db.supabase.get_service_client") as mock_sc, \
             patch("app.workers.settings.get_redis_pool") as mock_redis_pool:
            mock_client = MagicMock()
            mock_client.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"id": "1"}])
            mock_sc.return_value = mock_client


            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_redis_pool.return_value = mock_redis

            # Clear cache
            import app.main as main_mod
            main_mod._READINESS_CACHE = {"status": "ok", "timestamp": 0.0, "details": {}}

            res_ready = await client.get("/health/ready")
            assert res_ready.status_code == 200
            data = res_ready.json()
            assert data["status"] == "ok"
            assert data["details"]["database"] == "ok"
            assert data["details"]["redis"] == "ok"
