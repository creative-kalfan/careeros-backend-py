"""Tests for the job_intelligence background job."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.registry import clear_registry, get_job_definition
from app.workers.jobs.job_intelligence_job import analyze_job_intelligence_job
from app.models.job import NormalizedJob
from app.models.job_intelligence import JobIntelligence, SeniorityInfo, WorkArrangement
from app.repositories.job_repository import JobRepository
from app.repositories.job_intelligence_repository import JobIntelligenceRepository
from app.services.jobs.job_intelligence_service import JobIntelligenceService


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    clear_registry()
    yield
    clear_registry()


@pytest.mark.asyncio
async def test_job_is_registered() -> None:
    # Re-import to ensure decorators have run in this process.
    import importlib

    from app.workers.jobs import job_intelligence_job
    importlib.reload(job_intelligence_job)

    from app.workers.registry import get_job_definition

    definition = get_job_definition("analyze_job_intelligence")
    assert definition.name == "analyze_job_intelligence"
    assert definition.max_tries == 2
    assert definition.timeout == 120
    assert definition.retry is True


@pytest.mark.asyncio
async def test_successful_execution() -> None:
    job_id = "test-job-uuid"
    job_row = {
        "id": job_id,
        "external_job_id": "ext-1",
        "source_platform": "test",
        "title": "Engineer",
        "company": "Acme",
        "description": "Python developer role.",
        "location": "Remote",
        "url": "https://example.com",
    }
    intelligence = JobIntelligence(
        job_id=job_id,
        skills=[],
        requirements=[],
        seniority=SeniorityInfo(level="entry", confidence="high"),
        work_arrangement=WorkArrangement(type="remote", confidence="high"),
    )

    mock_job_repo = MagicMock(spec=JobRepository)
    mock_job_repo.get_job.return_value = job_row
    mock_intel_repo = MagicMock(spec=JobIntelligenceRepository)
    mock_intel_repo.upsert.return_value = {}

    with patch(
        "app.workers.jobs.job_intelligence_job.JobRepository",
        return_value=mock_job_repo,
    ), patch(
        "app.workers.jobs.job_intelligence_job.JobIntelligenceRepository",
        return_value=mock_intel_repo,
    ), patch(
        "app.workers.jobs.job_intelligence_job.JobIntelligenceService"
    ) as MockService:
        MockService.return_value.analyze_job.return_value = intelligence
        ctx: dict[str, Any] = {"job_id": "ctx-job-id"}
        result = await analyze_job_intelligence_job(ctx, job_id)
        assert result["success"] is True
        assert result["job_id"] == job_id
        MockService.return_value.analyze_job.assert_called_once()


@pytest.mark.asyncio
async def test_missing_job() -> None:
    job_id = "missing-job"
    mock_job_repo = MagicMock(spec=JobRepository)
    mock_job_repo.get_job.return_value = None

    with patch(
        "app.workers.jobs.job_intelligence_job.JobRepository",
        return_value=mock_job_repo,
    ), patch(
        "app.workers.jobs.job_intelligence_job.JobIntelligenceRepository"
    ) as MockIntelRepo, patch(
        "app.workers.jobs.job_intelligence_job.JobIntelligenceService"
    ) as MockService:
        ctx: dict[str, Any] = {"job_id": "ctx-job-id"}
        result = await analyze_job_intelligence_job(ctx, job_id)
        assert result["success"] is False
        assert result["error"] == "job not found"
        MockService.return_value.analyze_job.assert_not_called()
        # Repository is instantiated before the existence check in the worker.
        MockIntelRepo.assert_called_once()


@pytest.mark.asyncio
async def test_parser_failure_logs_and_raises() -> None:
    job_id = "test-job-uuid"
    job_row = {
        "id": job_id,
        "external_job_id": "ext-1",
        "source_platform": "test",
        "title": "Engineer",
        "company": "Acme",
        "description": "Python developer role.",
        "location": "Remote",
        "url": "https://example.com",
    }

    mock_job_repo = MagicMock(spec=JobRepository)
    mock_job_repo.get_job.return_value = job_row

    with patch(
        "app.workers.jobs.job_intelligence_job.JobRepository",
        return_value=mock_job_repo,
    ), patch(
        "app.workers.jobs.job_intelligence_job.JobIntelligenceRepository"
    ), patch(
        "app.workers.jobs.job_intelligence_job.JobIntelligenceService"
    ) as MockService:
        MockService.return_value.analyze_job.side_effect = RuntimeError("parse failed")
        with pytest.raises(RuntimeError, match="parse failed"):
            await analyze_job_intelligence_job({"job_id": "ctx"}, job_id)
