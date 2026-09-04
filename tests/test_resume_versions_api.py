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


def test_resume_repository_set_master_version():
    """Verify set_master_version unsets previous master and sets target version to master."""
    mock_client = MagicMock()
    table_mock = MagicMock()
    mock_client.table.return_value = table_mock

    target_row = {
        "id": TEST_VERSION_ID,
        "resume_id": TEST_RESUME_ID,
        "version_name": "New Master",
        "is_master": True,
        "status": "active",
        "content": {},
    }
    table_mock.update.return_value.eq.return_value.execute.return_value.data = [target_row]

    repo = ResumeRepository(client=mock_client)
    updated = repo.set_master_version(TEST_RESUME_ID, TEST_VERSION_ID)

    # Verify existing master was unset
    table_mock.update.assert_any_call({"is_master": False})
    table_mock.update.return_value.eq.assert_any_call("resume_id", TEST_RESUME_ID)

    # Verify target was set to master
    table_mock.update.assert_any_call({"is_master": True})
    table_mock.update.return_value.eq.assert_any_call("id", TEST_VERSION_ID)
    assert updated["is_master"] is True


def test_set_master_version_api_route(client):
    """Verify POST /api/resumes/versions/{version_id}/set-master delegates to repo.set_master_version."""
    mock_version = {
        "id": TEST_VERSION_ID,
        "resume_id": TEST_RESUME_ID,
        "version_name": "V2",
        "is_master": False,
        "content": {},
        "created_at": "2026-09-02T10:00:00Z",
        "updated_at": "2026-09-02T10:00:00Z",
    }
    mock_resume = {
        "id": TEST_RESUME_ID,
        "user_id": TEST_USER_ID,
        "title": "My Resume",
    }
    mock_updated_version = dict(mock_version, is_master=True)

    with patch.object(ResumeRepository, "get_version", return_value=mock_version), \
         patch.object(ResumeRepository, "get_resume", return_value=mock_resume), \
         patch.object(ResumeRepository, "set_master_version", return_value=mock_updated_version) as mock_set_master:
        response = client.post(f"/api/resumes/versions/{TEST_VERSION_ID}/set-master")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["is_master"] is True
        mock_set_master.assert_called_once_with(TEST_RESUME_ID, TEST_VERSION_ID)


def test_ats_repository_version_id_handling():
    """Verify ATSReportRepository preserves version_id on create, get, and list."""
    from app.repositories.ats_repository import ATSReportRepository
    from app.models.ats import ATSAnalysisReport
    from datetime import datetime

    mock_client = MagicMock()
    table_mock = MagicMock()
    mock_client.table.return_value = table_mock

    repo = ATSReportRepository(supabase_client=mock_client)
    now = datetime.now()

    report = ATSAnalysisReport(
        id="rep-1",
        resume_id="res-1",
        version_id="ver-42",
        job_title="Software Engineer",
        company="Tech Corp",
        job_description="Python dev",
        parsed_job_data={},
        overall_score=85.0,
        keyword_match_score=80.0,
        skills_match_score=90.0,
        experience_relevance_score=85.0,
        qualification_match_score=80.0,
        structure_format_score=90.0,
        matched_keywords=["python"],
        missing_keywords=[],
        partial_keywords=[],
        matched_skills=["python"],
        missing_skills=[],
        partial_skills=[],
        requirement_analysis=[],
        recommendations=[],
        high_priority_recommendations=[],
        medium_priority_recommendations=[],
        low_priority_recommendations=[],
        template_analysis={},
        section_analysis={},
        analysis_explanation={},
        scoring_version="v2",
        created_at=now,
        updated_at=now,
    )

    # 1. Test create_report writes version_id to data payload
    table_mock.insert.return_value.execute.return_value.data = [{"id": "rep-1"}]
    repo.create_report(report)
    inserted_data = table_mock.insert.call_args[0][0]
    assert inserted_data["version_id"] == "ver-42"

    # 2. Test get_report populates version_id
    db_row = dict(inserted_data)
    db_row["created_at"] = now.isoformat()
    db_row["updated_at"] = now.isoformat()
    table_mock.select.return_value.eq.return_value.execute.return_value.data = [db_row]

    fetched = repo.get_report("rep-1")
    assert fetched is not None
    assert fetched.version_id == "ver-42"

    # 3. Test list_reports_for_resume populates version_id
    table_mock.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [db_row]
    reports = repo.list_reports_for_resume("res-1")
    assert len(reports) == 1
    assert reports[0].version_id == "ver-42"

