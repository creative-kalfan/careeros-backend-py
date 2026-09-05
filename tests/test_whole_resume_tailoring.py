"""Tests for Whole-Document AST Resume Tailoring & Closed-Loop Compilation."""

import pytest
from app.models.resume import (
    BulletItem,
    ExperienceItem,
    PersonalInfo,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from app.services.optimization.whole_resume_tailoring_service import (
    whole_resume_tailoring_service,
)
from app.schemas.optimization import TailorResumeResponse


def sample_resume_content() -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(
                full_name="Jane Doe",
                email="jane@example.com",
                phone="+1234567890",
                location="San Francisco, CA",
            ),
            summary="Senior Software Engineer with 6 years building distributed systems.",
            skills=SkillCategory(
                technical=["Python", "FastAPI", "PostgreSQL", "Docker", "AWS", "Redis"],
                tools=["Git", "Jira"],
                soft_skills=["Leadership", "Communication"],
            ),
            experience=[
                ExperienceItem(
                    company="Acme Corp",
                    role="Senior Backend Engineer",
                    start_date="2021-01",
                    end_date="2024-01",
                    responsibilities=[
                        BulletItem(text="Architected high-throughput microservices handling 10k RPS."),
                        BulletItem(text="Led database migration reducing query latency by 40%."),
                    ],
                    tools=["Python", "PostgreSQL", "Redis"],
                )
            ],
            education=[],
        )
    )


def test_whole_resume_tailoring_service_deterministic() -> None:
    content = sample_resume_content()
    jd = (
        "We are looking for a Lead Python Developer with deep experience in FastAPI, "
        "AWS, PostgreSQL, microservices architecture, and team leadership to scale our backend."
    )

    result = whole_resume_tailoring_service.tailor_resume(
        resume_content=content,
        job_description=jd,
        job_title="Lead Python Developer",
        company="Tech Innovations",
    )

    assert isinstance(result, TailorResumeResponse)
    assert result.success is True
    assert len(result.plan) > 0
    assert result.score_comparison is not None
    assert result.score_comparison.baseline_score >= 0
    assert result.score_comparison.tailored_score >= result.score_comparison.baseline_score
    assert result.tailored_profile.get("summary") is not None
    assert "Lead Python Developer" in result.tailored_profile["summary"]


def test_whole_resume_tailoring_empty_jd_raises() -> None:
    content = sample_resume_content()
    with pytest.raises(ValueError):
        whole_resume_tailoring_service.tailor_resume(
            resume_content=content,
            job_description="   ",
        )


def test_post_optimization_tailor_api() -> None:
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.service import AuthContext, AuthUser
    from app.dependencies import get_current_user

    user = AuthUser(id="user-123", email="user@example.com")
    auth_ctx = AuthContext(user=user, supabase=MagicMock(), jwt="fake-jwt-token")
    app.dependency_overrides[get_current_user] = lambda: auth_ctx

    client = TestClient(app)
    try:
        payload = {
            "jobDescription": "Looking for a Lead Python Developer with FastAPI, Docker, and PostgreSQL experience.",
            "jobTitle": "Lead Python Developer",
            "company": "ScaleTech",
            "content": sample_resume_content().to_dict(),
        }
        res = client.post("/api/optimization/tailor", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") is True
        assert "plan" in data
        assert "tailoredProfile" in data
        assert "scoreComparison" in data
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_post_versions_apply_tailoring_api() -> None:
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.service import AuthContext, AuthUser
    from app.dependencies import get_current_user
    from app.repositories.resume_repository import ResumeRepository
    from app.services.resumes.compiler_service import resume_compiler_service

    user = AuthUser(id="user-123", email="user@example.com")
    auth_ctx = AuthContext(user=user, supabase=MagicMock(), jwt="fake-jwt-token")
    app.dependency_overrides[get_current_user] = lambda: auth_ctx

    client = TestClient(app)
    mock_resume = {
        "id": "resume-123",
        "user_id": "user-123",
        "title": "My Master Resume",
        "content": sample_resume_content().to_dict(),
    }
    mock_created_ver = {
        "id": "ver-new-123",
        "resume_id": "resume-123",
        "version_name": "Lead Python Developer Version (Sep 05)",
        "source": "tailoring",
        "content": sample_resume_content().to_dict(),
        "meta": {"storage_path": "user-123/versions/ver-new-123.pdf"},
        "status": "active",
        "is_master": False,
        "created_at": "2026-09-05T10:00:00Z",
        "updated_at": "2026-09-05T10:00:00Z",
    }
    mock_compile_res = {
        "storage_path": "user-123/versions/ver-new-123.pdf",
        "docx_storage_path": "user-123/versions/ver-new-123.docx",
        "geometry": {"pages": []},
        "strategy": "document_compiler",
    }

    try:
        with patch.object(ResumeRepository, "get_resume", return_value=mock_resume), \
             patch.object(ResumeRepository, "create_version", return_value=mock_created_ver), \
             patch.object(ResumeRepository, "update_version", return_value=mock_created_ver), \
             patch.object(resume_compiler_service, "compile_and_persist", return_value=mock_compile_res):

            payload = {
                "version_name": "Lead Python Developer Version (Sep 05)",
                "tailored_profile": sample_resume_content().profile.to_dict(),
                "job_description": "FastAPI, PostgreSQL and AWS developer.",
                "job_title": "Lead Python Developer",
            }
            res = client.post("/api/resumes/resume-123/versions/apply-tailoring", json=payload)
            assert res.status_code == 200
            json_res = res.json()
            assert json_res.get("success") is True
            assert json_res["data"]["id"] == "ver-new-123"
    finally:
        app.dependency_overrides.pop(get_current_user, None)

