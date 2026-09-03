"""Tests for resume versions API and job-specific version source provenance."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_user
from app.repositories.resume_repository import ResumeRepository

TEST_USER_ID = "user-uuid-1234"
TEST_RESUME_ID = "resume-uuid-5678"
TEST_VERSION_ID = "ver-uuid-9999"

@pytest.fixture
def auth_override():
    user = AuthUser(id=TEST_USER_ID, email="test@example.com")
    auth_ctx = AuthContext(user=user, supabase=MagicMock(), jwt="fake-jwt-token")
    app.dependency_overrides[get_current_user] = lambda: auth_ctx
    yield auth_ctx
    app.dependency_overrides.pop(get_current_user, None)

@pytest.fixture
def client(auth_override):
    return TestClient(app)

def test_create_job_specific_version_api(client):
    """Verify POST /api/resumes/{id}/versions accepts source='job_specific' and returns correct provenance."""
    mock_resume = {
        "id": TEST_RESUME_ID,
        "user_id": TEST_USER_ID,
        "title": "Master Resume",
        "content": {"profile": {"personal": {"full_name": "Jane Doe"}}},
    }
    mock_created_version = {
        "id": TEST_VERSION_ID,
        "resume_id": TEST_RESUME_ID,
        "version_name": "Senior Backend Engineer at Stripe",
        "source": "job_specific",
        "content": {"profile": {"personal": {"full_name": "Jane Doe"}}},
        "target_job_id": "job-stripe-1",
        "target_job_title": "Senior Backend Engineer",
        "target_company": "Stripe",
        "target_job_url": "https://stripe.com/jobs/1",
        "job_description": "Build payment infrastructure in Python/Go.",
        "template": "minimal",
        "status": "active",
        "is_master": False,
        "parent_version_id": None,
        "meta": {"target_job_title": "Senior Backend Engineer"},
        "last_ats_score": None,
        "last_analyzed_at": None,
        "sections_config": {},
        "created_at": "2026-09-02T10:00:00Z",
        "updated_at": "2026-09-02T10:00:00Z",
    }

    with patch.object(ResumeRepository, "get_resume", return_value=mock_resume), \
         patch.object(ResumeRepository, "create_version", return_value=mock_created_version):
        response = client.post(
            f"/api/resumes/{TEST_RESUME_ID}/versions",
            json={
                "version_name": "Senior Backend Engineer at Stripe",
                "source": "job_specific",
                "target_job_id": "job-stripe-1",
                "target_job_title": "Senior Backend Engineer",
                "target_company": "Stripe",
                "target_job_url": "https://stripe.com/jobs/1",
                "job_description": "Build payment infrastructure in Python/Go.",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        version = data["data"]
        assert version["id"] == TEST_VERSION_ID
        assert version["source"] == "job_specific"
        assert version["target_job_title"] == "Senior Backend Engineer"
        assert version["target_company"] == "Stripe"
        assert version["job_description"] == "Build payment infrastructure in Python/Go."

def test_resume_repository_constraint_fallback():
    """Verify repository falls back to meta.provenance_source when DB check constraint rejects source."""
    mock_client = MagicMock()
    first_call = True
    def mock_insert(payload):
        nonlocal first_call
        mock_builder = MagicMock()
        if first_call:
            first_call = False
            mock_builder.execute.side_effect = Exception(
                "new row for relation 'resume_versions' violates check constraint 'resume_versions_source_check' (23514)"
            )
        else:
            mock_builder.execute.return_value.data = [{
                "id": TEST_VERSION_ID,
                "resume_id": TEST_RESUME_ID,
                "version_name": payload["version_name"],
                "source": payload["source"],
                "content": payload["content"],
                "target_job_title": payload["target_job_title"],
                "target_company": payload["target_company"],
                "meta": payload["meta"],
            }]
        return mock_builder

    mock_client.table.return_value.insert = mock_insert

    repo = ResumeRepository(client=mock_client)
    version = repo.create_version(
        resume_id=TEST_RESUME_ID,
        content={},
        version_name="Test Version",
        source="job_specific",
        target_job_title="Staff Engineer",
        target_company="Anthropic",
    )

    assert version is not None
    assert version["source"] == "job_specific"
    assert version["meta"]["provenance_source"] == "job_specific"

def test_resume_repository_coercion_on_read():
    """Verify get_version and list_versions restore provenance_source from meta."""
    mock_client = MagicMock()
    stored_row = {
        "id": TEST_VERSION_ID,
        "resume_id": TEST_RESUME_ID,
        "version_name": "Tailored Version",
        "source": "manual",
        "content": {},
        "meta": {"provenance_source": "job_specific"},
    }
    mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = stored_row
    repo = ResumeRepository(client=mock_client)
    fetched = repo.get_version(TEST_VERSION_ID)
    assert fetched["source"] == "job_specific"
