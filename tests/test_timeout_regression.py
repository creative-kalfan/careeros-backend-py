"""Regression tests for API timeout prevention (candidate pool boundedness and async thread offloading)."""

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.models.job import NormalizedJob
from app.services.jobs.job_relevance_service import JobRelevanceService
from app.dependencies import get_current_user, get_job_relevance_service


def test_candidate_retrieval_remains_single_pass_when_total_exceeds_pool_limit():
    """Ensure candidate retrieval does NOT perform a second, unbounded table refetch
    when total database jobs exceed CANDIDATE_POOL_LIMIT (e.g. total=2952, limit=1000)."""
    mock_job_repo = MagicMock()
    fake_jobs = [
        NormalizedJob(
            external_job_id=str(i),
            title=f"Engineer {i}",
            company="Acme Corp",
            role_category="Engineering",
        ).model_dump()
        for i in range(10)
    ]
    # Simulate DB having 2,952 active jobs, returning 10 rows for candidate pool
    mock_job_repo.list_jobs.return_value = (fake_jobs, 2952)

    mock_profile_repo = MagicMock()
    mock_profile_repo.get_profile.return_value = None

    service = JobRelevanceService(
        job_repository=mock_job_repo,
        profile_repository=mock_profile_repo,
    )

    jobs, total = service.get_relevant_jobs(
        user_id=None,
        page=1,
        page_size=20,
        sort="best-match",
    )

    # 1. Candidate pool fetch must be called EXACTLY once (no second refetch of 2952 rows)
    assert mock_job_repo.list_jobs.call_count == 1
    call_kwargs = mock_job_repo.list_jobs.call_args.kwargs
    assert call_kwargs["page_size"] == 1000
    assert call_kwargs["page"] == 1

    # 2. Total must accurately reflect the candidate universe to prevent premature empty pages
    assert total == 10
    assert len(jobs) == 10


def test_async_personalized_jobs_route_dispatches_cleanly():
    """Verify GET /jobs/personalized returns 200 without blocking."""
    client = TestClient(app)
    mock_service = MagicMock()
    mock_service.get_relevant_jobs.return_value = ([], 2952)

    app.dependency_overrides[get_job_relevance_service] = lambda: mock_service
    app.dependency_overrides[get_current_user] = lambda: MagicMock(user=MagicMock(id="user-123"))

    try:
        response = client.get("/jobs/personalized?page=1&pageSize=20&sort=best-match")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["meta"]["total"] == 2952
        mock_service.get_relevant_jobs.assert_called_once()
    finally:
        app.dependency_overrides.clear()
