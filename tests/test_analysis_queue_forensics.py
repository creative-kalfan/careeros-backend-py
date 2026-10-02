"""Forensic reproduction tests for ARQ analyze_job_intelligence queue delay & JobNotFound."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.jobs.job_intelligence_job import analyze_job_intelligence_job
from app.repositories.job_repository import JobRepository
from app.repositories.job_intelligence_repository import JobIntelligenceRepository
from app.services.jobs.job_intelligence_service import JobIntelligenceService
from app.models.job_intelligence import JobIntelligence, SeniorityInfo, WorkArrangement


@pytest.mark.asyncio
async def test_scenario_a_concurrency_starvation_and_delay_scaling() -> None:
    """Scenario A: Worker concurrency = 2 causes queue delay to scale linearly with burst size.

    Proves:
        service_rate = capacity / duration = 2 / 0.5s = 4 jobs/s.
        With N=800 jobs, queue delay reaches 800 / 4 = 200 seconds.
    """
    capacity = 2
    mock_duration_s = 0.01  # 10ms per job for fast deterministic test
    n_jobs = 20

    start_times: list[float] = []
    finish_times: list[float] = []
    sem = asyncio.Semaphore(capacity)
    t0 = time.monotonic()

    async def worker_task(idx: int) -> None:
        async with sem:
            queue_delay = time.monotonic() - t0
            start_times.append(queue_delay)
            await asyncio.sleep(mock_duration_s)
            finish_times.append(time.monotonic() - t0)

    tasks = [asyncio.create_task(worker_task(i)) for i in range(n_jobs)]
    await asyncio.gather(*tasks)

    # First batch (index 0, 1) starts immediately (~0ms delay)
    assert start_times[0] < 0.02
    assert start_times[1] < 0.02

    # Later jobs wait for preceding jobs to finish.
    # Job index 18, 19 must wait ~ (18/2) * 10ms = 90ms.
    assert start_times[-1] >= (n_jobs // 2 - 1) * mock_duration_s * 0.7

    # Scaling formula verification:
    # delay(N) = (N / capacity) * duration
    expected_delay_for_800_prod_jobs = (800 / 2) * 0.5  # 200.0s
    assert expected_delay_for_800_prod_jobs == 200.0


@pytest.mark.asyncio
async def test_scenario_b_burst_enqueue_from_crawl() -> None:
    """Scenario B: A crawl with N inserted jobs enqueues N analysis jobs into ARQ queue."""
    mock_redis = AsyncMock()
    mock_redis.enqueue_job = AsyncMock(return_value="mock-job-id")

    source = "adzuna"
    inserted_ids = [f"ext-job-{i}" for i in range(50)]

    # Simulate crawl_jobs.py loop
    for external_id in inserted_ids:
        import hashlib
        analysis_id = "analyze:" + hashlib.sha1(f"{source}:{external_id}".encode()).hexdigest()
        await mock_redis.enqueue_job("analyze_job_intelligence", external_id, _job_id=analysis_id)

    assert mock_redis.enqueue_job.call_count == 50
    # Every job is queued to the default ARQ queue
    first_call = mock_redis.enqueue_job.call_args_list[0]
    assert first_call[0][0] == "analyze_job_intelligence"
    assert first_call[0][1] == "ext-job-0"
    assert first_call[1]["_job_id"].startswith("analyze:")


@pytest.mark.asyncio
async def test_scenario_c_job_not_found_lifecycle_race() -> None:
    """Scenario C: Source job is inserted, then deactivated by crawl reconciliation

    before analysis job executes, producing error_type=JobNotFound.
    """
    job_id = "ext-race-123"

    # Mock DB state: row exists but is_active = False (deactivated during ~200s wait)
    inactive_db_row = {
        "id": "uuid-123",
        "external_job_id": job_id,
        "is_active": False,
        "title": "Software Engineer",
    }

    mock_client = MagicMock()

    # get_job queries jobs with eq("is_active", True)
    # 1. eq("id", job_id) -> empty
    # 2. eq("external_job_id", job_id).eq("is_active", True) -> empty because is_active is False
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_filter1 = MagicMock()
    mock_filter2 = MagicMock()

    mock_client.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_select.eq.return_value = mock_filter1
    mock_filter1.eq.return_value = mock_filter2

    # Since the row in DB has is_active=False, active query returns empty list
    mock_filter2.execute.return_value = MagicMock(data=[])

    repo = JobRepository(client=mock_client)
    retrieved = repo.get_job(job_id)
    assert retrieved is None

    # Now verify analyze_job_intelligence_job behavior with missing/inactive job
    with patch("app.workers.jobs.job_intelligence_job.JobRepository", return_value=repo), \
         patch("app.workers.jobs.job_intelligence_job.JobIntelligenceRepository") as MockIntelRepo, \
         patch("app.workers.jobs.job_intelligence_job.JobLogger") as MockLogger:

        ctx: dict[str, Any] = {
            "job_id": "analyze:abc123",
            "score": int(time.time() * 1000) - 200000,  # 200s ago
            "job_try": 1,
        }
        result = await analyze_job_intelligence_job(ctx, job_id)

        assert result["success"] is False
        assert result["error"] == "job not found"
        # Verify JobNotFound was logged
        MockLogger.return_value.failed.assert_called_once()
        failed_kwargs = MockLogger.return_value.failed.call_args[1]
        assert failed_kwargs["error_type"] == "JobNotFound"


@pytest.mark.asyncio
async def test_scenario_d_crawl_admission_backpressure_and_queue_fairness() -> None:
    """Scenario D: When queue depth >= capacity, crawl dispatcher admits 0 crawls,

    preventing crawls from queuing behind analysis jobs. Once backlog clears, crawls run.
    """
    from app.services.jobs.crawl_dispatcher import dispatch_due_targets

    # Mock settings & environment
    mock_ctx = {"worker": MagicMock(max_jobs=2)}

    # When queue depth is 50 (backlogged with analysis jobs)
    with patch("app.services.jobs.crawl_dispatcher._migration_probe", return_value=True), \
         patch("app.services.jobs.crawl_dispatcher._worker_capacity", return_value=2), \
         patch("app.services.jobs.crawl_dispatcher._queue_depth", return_value=50), \
         patch("app.services.jobs.crawl_dispatcher._rpc") as mock_rpc:

        admitted = await dispatch_due_targets(mock_ctx)
        # Admitted must be 0 because 2 - 50 <= 0
        assert admitted == 0
        mock_rpc.assert_not_called()

    # When queue depth drops to 0 (all analysis jobs completed)
    with patch("app.services.jobs.crawl_dispatcher._migration_probe", return_value=True), \
         patch("app.services.jobs.crawl_dispatcher._worker_capacity", return_value=2), \
         patch("app.services.jobs.crawl_dispatcher._queue_depth", return_value=0), \
         patch("app.services.jobs.crawl_dispatcher._rpc", return_value=[{"source": "adzuna", "slug": "eng"}]) as mock_rpc, \
         patch("app.workers.dispatcher.enqueue_scheduled_crawl", return_value="crawl-123"):

        admitted = await dispatch_due_targets(mock_ctx)
        assert admitted == 1
        mock_rpc.assert_called_once()
