"""Tests for the Jobs API routes."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.main import app
from app.models.job import NormalizedJob
from app.services.jobs.job_relevance_service import JobRelevanceService
from app.dependencies import get_current_user


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_job_relevance_service():
    service = MagicMock()
    service.get_relevant_jobs.return_value = ([], 0)
    service.get_job.return_value = NormalizedJob(
        external_job_id="1",
        title="Software Engineer",
        company="Test Company",
        role_category="Software Engineering",
        match={
            "overall": 85,
            "skill_match": 90,
            "resume_match": 80,
            "experience_match": 85,
            "location_match": 90,
            "salary_match": 80,
            "company_preference": 100,
            "freshness": 90,
        }
    )
    return service


@pytest.fixture
def override_deps(client, mock_job_relevance_service):
    """Override FastAPI dependencies for the duration of a test."""
    from app.dependencies import get_job_relevance_service
    app.dependency_overrides[get_job_relevance_service] = lambda: mock_job_relevance_service
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def override_auth(client):
    """Override the auth dependency for the duration of a test."""
    app.dependency_overrides[get_current_user] = lambda: MagicMock(user=MagicMock(id="user-123"))
    yield
    app.dependency_overrides.clear()


def test_list_jobs(client, mock_job_relevance_service, override_deps):
    """Test listing all jobs."""
    mock_job_relevance_service.get_relevant_jobs.return_value = ([], 0)
    response = client.get("/jobs?page=1&page_size=20")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert isinstance(data["data"], list)
    assert data["meta"]["total"] == 0


def test_list_personalized_jobs(client, mock_job_relevance_service, override_deps, override_auth):
    """Test listing personalized jobs."""
    mock_job_relevance_service.get_relevant_jobs.return_value = ([], 0)
    response = client.get("/jobs/personalized?page=1&page_size=20")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert isinstance(data["data"], list)
    assert data["meta"]["total"] == 0


def test_get_job(client, mock_job_relevance_service, override_deps):
    """Test getting a single job."""
    mock_job = NormalizedJob(
        external_job_id="1",
        title="Software Engineer",
        company="Test Company",
        role_category="Software Engineering"
    )
    mock_job_relevance_service.get_job.return_value = mock_job
    response = client.get("/jobs/1")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["external_job_id"] == "1"
    assert data["data"]["title"] == "Software Engineer"


def test_get_job_not_found(client, mock_job_relevance_service, override_deps):
    """Test getting a non-existent job."""
    mock_job_relevance_service.get_job.return_value = None
    response = client.get("/jobs/999")

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert "error" in data
    assert data["error"]["message"] == "Job not found"