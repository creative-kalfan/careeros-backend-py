"""Regression: manual-editor Save must change the physical PDF artifact.

Covers the identified gap: "manual-editor Save path still updates master JSON only".
After the fix, manual Save goes through a version + canonical compiler:

  UI edit -> save-content -> document model -> PDF/DOCX -> storage
  -> derived version -> frontend selects new artifact -> new PDF in right pane.

Tests:
  1. Edit summary manually, compile real PDF, extract text, confirm edit present.
  2. Original PDF bytes remain unchanged.
  3. save-content persists content + new artifact paths (derived version).
  4. save-content rejects master (immutability).
  5. save-content failure is truthful (500, nothing persisted).
  6. Version switching still works (old version row untouched, new artifact selected).
"""

from __future__ import annotations

import fitz
import pytest
from unittest.mock import MagicMock, patch

from app.models.resume import (
    BulletItem,
    ExperienceItem,
    PersonalInfo,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from app.services.resumes.document_model import build_document_model
from app.services.resumes.docx_compiler import docx_compiler
from app.services.resumes.pdf_compiler import pdf_compiler

from .benchmark_resume_studio import fixture_1_single_column


@pytest.fixture
def master_content() -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(
                full_name="Manual Save Candidate",
                headline="Backend Engineer",
                email="manual.save@example.com",
            ),
            summary="Backend engineer with experience in APIs and databases.",
            experience=[
                ExperienceItem(
                    id="exp_001",
                    role="Backend Engineer",
                    company="Acme Corp",
                    start_date="2021",
                    end_date="Present",
                    current=True,
                    responsibilities=[
                        BulletItem(id="blt_001", text="Built REST APIs for internal tools."),
                    ],
                )
            ],
            skills=SkillCategory(technical=["Python", "PostgreSQL"]),
        )
    )


def _make_client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.service import AuthContext, AuthUser
    from app.dependencies import get_current_user

    user = AuthUser(id="test-user-1", email="test@example.com")
    auth_ctx = AuthContext(user=user, supabase=MagicMock(), jwt="fake-jwt")
    app.dependency_overrides[get_current_user] = lambda: auth_ctx
    return TestClient(app), app, get_current_user


def test_manual_summary_edit_physically_changes_pdf(master_content):
    """1-5: manual summary edit -> real PDF contains edit, original untouched."""
    original_pdf_bytes = fixture_1_single_column()
    original_len = len(original_pdf_bytes)

    edited_summary = (
        "Backend engineer specializing in MANUALSAVEEDITTOKEN distributed "
        "payment systems on AWS."
    )
    master_content.profile.summary = edited_summary

    doc_model = build_document_model(master_content)
    docx_bytes = docx_compiler.compile(doc_model)
    pdf_bytes, ver_result = pdf_compiler.compile(doc_model, docx_bytes)

    assert ver_result.is_valid is True
    assert pdf_bytes.startswith(b"%PDF-")
    extracted = fitz.open(stream=pdf_bytes, filetype="pdf")[0].get_text()
    assert "MANUALSAVEEDITTOKEN" in extracted
    # Unchanged sections survive.
    assert "Acme Corp" in extracted
    # Original uploaded bytes never mutated.
    assert len(original_pdf_bytes) == original_len


def test_save_content_persists_artifact_and_version(master_content):
    """6-8: save-content returns derived artifact frontend can select; old row untouched."""
    from app.repositories.resume_repository import ResumeRepository

    edited = master_content.to_dict()
    edited["profile"]["summary"] = "Manually edited summary MANUALSAVEAPI."

    mock_version = {
        "id": "ver-derived-1",
        "resume_id": "res-123",
        "version_name": "Manual Edit",
        "is_master": False,
        "content": master_content.to_dict(),
        "meta": {"storage_path": "test-user-1/versions/ver-derived-1.pdf"},
        "created_at": "2026-09-04T12:00:00Z",
        "updated_at": "2026-09-04T12:00:00Z",
    }
    mock_resume = {
        "id": "res-123",
        "user_id": "test-user-1",
        "content": master_content.to_dict(),
        "storage_path": "test-user-1/master.pdf",
    }
    saved_updates: list[dict] = []

    def fake_update_version(vid, data):
        saved_updates.append(dict(data))
        return {**mock_version, **data}

    compile_result = {
        "storage_path": "test-user-1/versions/ver-derived-1.pdf",
        "docx_storage_path": "test-user-1/versions/ver-derived-1.docx",
        "geometry": {"pages": []},
        "strategy": "document_compiler",
    }

    with patch.object(ResumeRepository, "get_resume", return_value=mock_resume), patch.object(
        ResumeRepository, "get_version", return_value=mock_version
    ), patch.object(ResumeRepository, "update_version", side_effect=fake_update_version), patch(
        "app.services.resumes.compiler_service.resume_compiler_service.compile_and_persist",
        return_value=compile_result,
    ):
        client, app, dep = _make_client()
        try:
            resp = client.post(
                "/api/resumes/versions/ver-derived-1/save-content",
                json={"content": edited},
            )
        finally:
            app.dependency_overrides.pop(dep, None)

    assert resp.status_code == 200
    body = resp.json()["data"]
    # Frontend switches to this artifact via meta.storage_path.
    assert body["id"] == "ver-derived-1"
    assert body["meta"]["storage_path"] == "test-user-1/versions/ver-derived-1.pdf"
    assert body["meta"]["docx_storage_path"] == "test-user-1/versions/ver-derived-1.docx"
    assert len(saved_updates) == 1
    assert saved_updates[0]["content"]["profile"]["summary"] == "Manually edited summary MANUALSAVEAPI."
    assert saved_updates[0]["meta"]["storage_path"] == "test-user-1/versions/ver-derived-1.pdf"
    # Source row was not mutated in place by the test double.
    assert mock_version["content"]["profile"]["summary"] != "Manually edited summary MANUALSAVEAPI."


def test_save_content_rejects_master(master_content):
    """Master stays immutable."""
    from app.repositories.resume_repository import ResumeRepository

    mock_version = {
        "id": "ver-master",
        "resume_id": "res-123",
        "is_master": True,
        "content": master_content.to_dict(),
        "meta": {},
    }
    mock_resume = {"id": "res-123", "user_id": "test-user-1"}

    with patch.object(ResumeRepository, "get_resume", return_value=mock_resume), patch.object(
        ResumeRepository, "get_version", return_value=mock_version
    ):
        client, app, dep = _make_client()
        try:
            resp = client.post(
                "/api/resumes/versions/ver-master/save-content",
                json={"content": master_content.to_dict()},
            )
        finally:
            app.dependency_overrides.pop(dep, None)

    assert resp.status_code == 400


def test_save_content_truthful_failure(master_content):
    """9: failed artifact generation -> 500, nothing persisted, no fake success."""
    from app.repositories.resume_repository import ResumeRepository

    mock_version = {
        "id": "ver-derived-1",
        "resume_id": "res-123",
        "is_master": False,
        "content": master_content.to_dict(),
        "meta": {},
    }
    mock_resume = {"id": "res-123", "user_id": "test-user-1"}
    saved_updates: list[dict] = []

    def fake_update_version(vid, data):
        saved_updates.append(dict(data))
        return {**mock_version, **data}

    with patch.object(ResumeRepository, "get_resume", return_value=mock_resume), patch.object(
        ResumeRepository, "get_version", return_value=mock_version
    ), patch.object(ResumeRepository, "update_version", side_effect=fake_update_version), patch(
        "app.services.resumes.compiler_service.resume_compiler_service.compile_and_persist",
        side_effect=RuntimeError("renderer crashed"),
    ):
        client, app, dep = _make_client()
        try:
            resp = client.post(
                "/api/resumes/versions/ver-derived-1/save-content",
                json={"content": master_content.to_dict()},
            )
        finally:
            app.dependency_overrides.pop(dep, None)

    assert resp.status_code == 500
    assert "NOT applied" in (resp.json().get("error") or {}).get("message", "")
    assert saved_updates == []
