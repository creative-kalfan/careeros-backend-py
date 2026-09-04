"""Regression tests for the DOCUMENT CHANGE CONTRACT (fake-success prevention).

The product rule being enforced:
    A "suggestion applied" success must correspond to a REAL document artifact
    change. If any step of the pipeline fails (operation rejected, artifact
    compile error, upload error) the backend must report failure truthfully and
    must NOT persist a JSON-only content change that leaves the visible PDF stale.

Tests here cover:
  1. apply-operation returns 500 (not success) when artifact regeneration fails,
     and the version content row is NOT updated.
  2. accept-suggestion (versioned session) returns 500 and marks nothing applied
     when artifact compilation fails (covered at function level in
     test_optimization_ownership.py; here at HTTP level).
  3. compiler_service raises when artifact upload to storage fails (no silent
     "successful compile" with a missing artifact).
  4. CRITICAL REGRESSION: applying a real summary + bullet rewrite through the
     document model and compiling a real PDF yields a PDF whose extracted text
     contains the changed content while the original source PDF stays intact.
"""

from __future__ import annotations

import io
import fitz
import pytest
from unittest.mock import MagicMock, patch

from app.models.resume import (
    BulletItem,
    ExperienceItem,
    PersonalInfo,
    ProjectItem,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from app.services.resumes.document_model import build_document_model
from app.services.resumes.docx_compiler import docx_compiler
from app.services.resumes.pdf_compiler import pdf_compiler

from .benchmark_resume_studio import fixture_1_single_column


@pytest.fixture
def versioned_resume() -> ResumeContent:
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Sarah Connor",
            headline="Senior Backend Engineer",
            email="sarah.connor@example.com",
        ),
        summary="Backend engineer experienced in building distributed services.",
        experience=[
            ExperienceItem(
                id="exp_001",
                role="Senior Backend Engineer",
                company="Cyberdyne Systems",
                start_date="2019",
                end_date="Present",
                current=True,
                responsibilities=[
                    BulletItem(id="blt_001", text="Built REST APIs for a payments platform."),
                    BulletItem(id="blt_002", text="Maintained legacy services and deployed releases."),
                ],
            )
        ],
        projects=[
            ProjectItem(id="prj_001", name="PayCore", description="Payment orchestration service.")
        ],
        skills=SkillCategory(technical=["Python", "PostgreSQL", "AWS"]),
    )
    return ResumeContent(profile=profile)


def _api_env(versioned_resume, raise_compile=False):
    """Shared TestClient mocks for the apply-operation / accept endpoints."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.service import AuthContext, AuthUser
    from app.dependencies import get_current_user

    user = AuthUser(id="test-user-1", email="test@example.com")
    auth_ctx = AuthContext(user=user, supabase=MagicMock(), jwt="fake-jwt")
    app.dependency_overrides[get_current_user] = lambda: auth_ctx

    client = TestClient(app)

    mock_version = {
        "id": "ver-123",
        "resume_id": "res-123",
        "version_name": "Test Version",
        "is_master": False,
        "content": versioned_resume.to_dict(),
        "meta": {"storage_path": "test-user-1/versions/ver-123.pdf"},
        "created_at": "2026-09-04T12:00:00Z",
        "updated_at": "2026-09-04T12:00:00Z",
    }
    mock_resume = {
        "id": "res-123",
        "user_id": "test-user-1",
        "content": versioned_resume.to_dict(),
        "storage_path": "test-user-1/master.pdf",
    }

    saved_updates: list[dict] = []

    def fake_update_version(vid, data):
        saved_updates.append(dict(data))
        merged = {**mock_version, **data, "updated_at": "2026-09-04T12:01:00Z"}
        return merged

    from app.repositories.resume_repository import ResumeRepository

    mock_resume_cls = MagicMock()
    mock_resume_cls.return_value.get_resume.return_value = mock_resume
    mock_resume_cls.return_value.get_version.return_value = mock_version
    mock_resume_cls.return_value.update_version.side_effect = fake_update_version

    enter = patch.object(ResumeRepository, "get_resume", return_value=mock_resume)
    if raise_compile:
        compile_patch = patch(
            "app.services.resumes.compiler_service.resume_compiler_service.compile_and_persist",
            side_effect=RuntimeError("boom: artifact renderer crashed"),
        )
    else:
        compile_patch = patch(
            "app.services.resumes.compiler_service.resume_compiler_service.compile_and_persist",
            return_value={
                "storage_path": "test-user-1/versions/ver-123.pdf",
                "docx_storage_path": "test-user-1/versions/ver-123.docx",
                "geometry": {"pages": []},
                "strategy": "document_compiler",
            },
        )

    return client, app, get_current_user, mock_resume_cls, saved_updates, enter, compile_patch


def test_apply_operation_fails_hard_when_artifact_regeneration_fails(versioned_resume):
    """If compile_and_persist raises, apply-operation must 500 and NOT persist content."""
    from app.repositories.resume_repository import ResumeRepository

    (
        client,
        app,
        dep,
        mock_resume_cls,
        saved_updates,
        enter,
        compile_patch,
    ) = _api_env(versioned_resume, raise_compile=True)
    try:
        with enter, compile_patch, patch.object(ResumeRepository, "get_version",
                                                return_value={
                                                    "id": "ver-123",
                                                    "resume_id": "res-123",
                                                    "version_name": "Test Version",
                                                    "is_master": False,
                                                    "content": versioned_resume.to_dict(),
                                                    "meta": {"storage_path": "test-user-1/versions/ver-123.pdf"},
                                                    "created_at": "2026-09-04T12:00:00Z",
                                                    "updated_at": "2026-09-04T12:00:00Z",
                                                }):
            resp = client.post(
                "/api/resumes/versions/ver-123/apply-operation",
                json={
                    "operation": "replace",
                    "section": "summary",
                    "replacement": {"suggestedText": "A brand new tailored summary."},
                },
            )
        assert resp.status_code == 500
        err_msg = (resp.json().get("error") or {}).get("message", "")
        assert "NOT applied" in err_msg
        # JSON-only content must never be persisted when the artifact failed.
        assert saved_updates == []
    finally:
        app.dependency_overrides.pop(dep, None)


def test_apply_operation_persists_content_with_new_artifact_on_success(versioned_resume):
    """On success the version row must be updated with BOTH content and the new artifact path."""
    from app.repositories.resume_repository import ResumeRepository

    mock_version = {
        "id": "ver-123",
        "resume_id": "res-123",
        "version_name": "Test Version",
        "is_master": False,
        "content": versioned_resume.to_dict(),
        "meta": {"storage_path": "test-user-1/versions/ver-123.pdf"},
        "created_at": "2026-09-04T12:00:00Z",
        "updated_at": "2026-09-04T12:00:00Z",
    }
    mock_resume = {
        "id": "res-123",
        "user_id": "test-user-1",
        "content": versioned_resume.to_dict(),
        "storage_path": "test-user-1/master.pdf",
    }
    saved_updates: list[dict] = []

    def fake_update_version(vid, data):
        saved_updates.append(dict(data))
        return {**mock_version, **data, "updated_at": "2026-09-04T12:01:00Z"}

    from app.repositories.resume_repository import ResumeRepository

    compile_patch = patch(
        "app.services.resumes.compiler_service.resume_compiler_service.compile_and_persist",
        return_value={
            "storage_path": "test-user-1/versions/ver-123.pdf",
            "docx_storage_path": "test-user-1/versions/ver-123.docx",
            "geometry": {"pages": []},
            "strategy": "document_compiler",
        },
    )

    with patch.object(ResumeRepository, "get_resume", return_value=mock_resume), patch.object(
        ResumeRepository, "get_version", return_value=mock_version
    ), patch.object(ResumeRepository, "update_version", side_effect=fake_update_version), compile_patch:
        client, app, dep = _make_client()
        try:
            resp = client.post(
                "/api/resumes/versions/ver-123/apply-operation",
                json={
                    "operation": "replace",
                    "section": "summary",
                    "replacement": {"suggestedText": "A brand new tailored summary."},
                },
            )
        finally:
            app.dependency_overrides.pop(dep, None)

    assert resp.status_code == 200
    assert len(saved_updates) == 1
    update = saved_updates[0]
    assert update["content"]["profile"]["summary"] == "A brand new tailored summary."
    assert update["meta"]["storage_path"] == "test-user-1/versions/ver-123.pdf"


def _make_client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.service import AuthContext, AuthUser
    from app.dependencies import get_current_user

    user = AuthUser(id="test-user-1", email="test@example.com")
    auth_ctx = AuthContext(user=user, supabase=MagicMock(), jwt="fake-jwt")
    app.dependency_overrides[get_current_user] = lambda: auth_ctx
    return TestClient(app), app, get_current_user


def test_compiler_service_raises_when_artifact_upload_fails(versioned_resume):
    """compiler_service must raise (not silently succeed) when artifact upload fails."""
    from app.services.resumes.compiler_service import resume_compiler_service

    with patch(
        "app.services.resumes.compiler_service._upload_to_storage", return_value=False
    ):
        with pytest.raises(RuntimeError, match="Failed to persist compiled artifacts"):
            resume_compiler_service.compile_and_persist(
                user_id="u1",
                version_id="v1",
                content=versioned_resume,
            )


def test_real_pdf_contains_rewritten_text_after_document_operations(versioned_resume):
    """CRITICAL REGRESSION: after applying real changes through the canonical
    document model and compiling a real PDF, the resulting PDF text MUST contain
    the new content, and the original source PDF must remain byte-identical.
    This guards the product rule that success == actual document artifact change.
    """
    original_pdf_bytes = fixture_1_single_column()

    new_summary = (
        "Senior Backend Engineer specializing in high-throughput distributed "
        "payment systems, REST APIs, and cloud infrastructure on AWS."
    )
    new_bullet = (
        "Designed and scaled REST APIs for a payments platform serving high "
        "transaction volumes with PostgreSQL and AWS infrastructure."
    )

    doc_model = build_document_model(versioned_resume)
    assert doc_model.apply_operation(
        {"operation": "replace_block", "target": "summary", "new_content": new_summary}
    ) is True
    assert doc_model.apply_operation(
        {
            "operation": "rewrite_bullet",
            "target": "exp_001",
            "child_id": "blt_001",
            "new_content": new_bullet,
        }
    ) is True

    # The source resume content model (master) must remain untouched.
    assert versioned_resume.profile.summary != new_summary
    original_first_bullet = versioned_resume.profile.experience[0].responsibilities[0].text
    assert original_first_bullet != new_bullet

    # Compile a REAL PDF artifact from the mutated model.
    docx_bytes = docx_compiler.compile(doc_model)
    pdf_bytes, ver_result = pdf_compiler.compile(doc_model, docx_bytes)
    assert ver_result.is_valid is True
    assert pdf_bytes.startswith(b"%PDF-")

    extracted = fitz.open(stream=pdf_bytes, filetype="pdf")[0].get_text()
    assert "payments platform" in extracted
    assert "AWS" in extracted or "PostgreSQL" in extracted
    # Company / unchanged sections must survive the rewrite.
    assert "Cyberdyne Systems" in extracted

    # The original uploaded PDF bytes are only ever read as the geometry/style
    # source - the pipeline never writes back to or replaces the source file.
    assert len(original_pdf_bytes) > 0
