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


def test_mutate_pdf_api_success(client):
    """Verify POST /api/resumes/{resume_id}/versions/{version_id}/mutate-pdf calls PDFMutationEngine and derives version."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(54, 50, 400, 80), "ALEX MORGAN", fontsize=16, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()

    mock_resume = {
        "id": TEST_RESUME_ID,
        "user_id": TEST_USER_ID,
        "title": "Master Resume",
        "storage_path": f"{TEST_USER_ID}/master.pdf",
        "content": {"profile": {"personal": {"full_name": "ALEX MORGAN"}}},
    }
    mock_version = {
        "id": TEST_VERSION_ID,
        "resume_id": TEST_RESUME_ID,
        "version_name": "Initial Version",
        "source": "manual",
        "content": {"profile": {"personal": {"full_name": "ALEX MORGAN"}}},
        "meta": {"storage_path": f"{TEST_USER_ID}/master.pdf"},
    }
    mock_created_version = {
        "id": "new-version-uuid",
        "resume_id": TEST_RESUME_ID,
        "version_name": "Initial Version (Edited)",
        "source": "pdf_edit",
        "content": {"profile": {"personal": {"full_name": "JORDAN TAYLOR"}}},
        "meta": {"storage_path": f"{TEST_USER_ID}/versions/new-vid.pdf"},
    }

    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.download.return_value = pdf_bytes
    mock_bucket.upload.return_value = MagicMock()
    mock_storage.storage.from_.return_value = mock_bucket

    with patch.object(ResumeRepository, "get_resume", return_value=mock_resume), \
         patch.object(ResumeRepository, "get_version", return_value=mock_version), \
         patch.object(ResumeRepository, "create_version", return_value=mock_created_version), \
         patch("app.db.supabase.get_authenticated_client", return_value=mock_storage):

        response = client.post(
            f"/api/resumes/{TEST_RESUME_ID}/versions/{TEST_VERSION_ID}/mutate-pdf",
            json={
                "page_index": 0,
                "bbox": [54, 50, 400, 80],
                "replacement_text": "JORDAN TAYLOR",
                "section": "summary",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["source"] == "pdf_edit"
        assert mock_bucket.upload.called


def test_canonicalize_version_source_obeys_017_check():
    from app.repositories.resume_repository import canonicalize_version_source

    assert canonicalize_version_source("tailoring") == "job_specific"
    assert canonicalize_version_source("ai_tailoring") == "job_specific"
    assert canonicalize_version_source("document_compiler") == "manual"
    assert canonicalize_version_source("direct_pdf_mutation") == "manual"
    assert canonicalize_version_source("pdf_edit") == "manual"
    assert canonicalize_version_source("job_specific") == "job_specific"
    assert canonicalize_version_source("optimization") == "optimization"
    assert canonicalize_version_source(None) == "manual"


def test_create_version_writes_check_safe_source():
    repo = ResumeRepository(client=MagicMock())
    captured = {}

    def fake_insert(payload):
        captured["payload"] = payload
        class _Exec:
            def execute(self):
                row = dict(payload)
                row["id"] = "ver-1"
                result = MagicMock()
                result.data = [row]
                return result
        return _Exec()

    repo._client.table.return_value.insert.side_effect = fake_insert
    row = repo.create_version(
        resume_id="resume-1",
        content={},
        version_name="Tailored",
        source="tailoring",
        meta={"provenance_source": "tailoring"},
    )
    assert captured["payload"]["source"] == "job_specific"
    assert captured["payload"]["meta"]["provenance_source"] == "tailoring"
    assert row["source"] == "tailoring"


def test_update_version_strips_compiler_strategy_from_source():
    repo = ResumeRepository(client=MagicMock())
    captured = {}

    def fake_update(payload):
        captured["payload"] = payload
        class _Eq:
            def eq(self, *_args, **_kwargs):
                return self
            def execute(self):
                row = {"id": "ver-1", **payload}
                result = MagicMock()
                result.data = [row]
                return result
        return _Eq()

    repo._client.table.return_value.update.side_effect = fake_update
    row = repo.update_version("ver-1", {"source": "document_compiler", "meta": {"compilation_strategy": "document_compiler"}})
    assert captured["payload"]["source"] == "manual"
    assert captured["payload"]["meta"]["provenance_source"] == "document_compiler"
    assert captured["payload"]["meta"]["compilation_strategy"] == "document_compiler"
    assert row["source"] == "document_compiler"



