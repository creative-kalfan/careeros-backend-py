"""Tests for the Job Intelligence API routes."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def override_auth(client: TestClient) -> Any:
    app.dependency_overrides[get_current_user] = lambda: MagicMock(
        user=MagicMock(id="user-123")
    )
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mock_job_repo(client: TestClient) -> Any:
    mock_repo = MagicMock()
    mock_repo.get_job.return_value = {
        "id": "test-job",
        "external_job_id": "ext-1",
        "source_platform": "test",
        "title": "Engineer",
        "company": "Acme",
        "description": "Python developer role.",
        "location": "Remote",
        "url": "https://example.com",
    }
    return mock_repo


class TestJobIntelligenceAPI:
    def test_analyze_returns_queued(self, client: TestClient, override_auth: Any, mock_job_repo: Any) -> None:
        mock_job_id = "test-job-id"
        with patch("app.api.routes.jobs.enqueue", new_callable=AsyncMock) as mock_enqueue, \
             patch("app.api.routes.jobs.JobRepository", return_value=mock_job_repo):
            mock_enqueue.return_value = mock_job_id
            response = client.post(
                "/jobs/test-job/intelligence/analyze",
                headers={"Authorization": "Bearer fake-token"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["success"] is True
            assert body["data"]["status"] == "queued"
            assert body["data"]["analysis_job_id"] == mock_job_id

    def test_get_not_analyzed(self, client: TestClient, override_auth: Any) -> None:
        with patch(
            "app.api.routes.jobs.JobIntelligenceRepository"
        ) as MockRepo:
            MockRepo.return_value.get_by_job_id.return_value = None
            response = client.get(
                "/jobs/test-job/intelligence",
                headers={"Authorization": "Bearer fake-token"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["data"]["status"] == "not_analyzed"

    def test_get_returns_intelligence(self, client: TestClient, override_auth: Any) -> None:
        mock_row = {
            "id": "intel-1",
            "job_id": "test-job",
            "intelligence_version": "1.0",
            "generated_at": "2025-01-01T00:00:00Z",
            "seniority": {"level": "senior"},
            "skills": [{"name": "Python", "normalized_name": "python"}],
            "requirements": [],
            "education": [],
            "certifications": [],
            "keywords": ["python"],
            "responsibilities": [],
            "industries": [],
            "work_arrangement": {"type": "remote"},
        }
        with patch(
            "app.api.routes.jobs.JobIntelligenceRepository"
        ) as MockRepo:
            MockRepo.return_value.get_by_job_id.return_value = mock_row
            response = client.get(
                "/jobs/test-job/intelligence",
                headers={"Authorization": "Bearer fake-token"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["data"]["job_id"] == "test-job"
            assert body["data"]["seniority"]["level"] == "senior"
