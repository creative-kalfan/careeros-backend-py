"""Tests for CareerOS Resume Studio Core Architecture Correction."""

import pytest
from app.models.resume import (
    ResumeContent,
    ResumeProfile,
    PersonalInfo,
    ExperienceItem,
    BulletItem,
    EducationItem,
    SkillCategory,
    ProjectItem,
)
from app.services.optimization.optimization_service import OptimizationService
from app.api.routes.optimization import _apply_suggestion_to_content
from app.services.export_service import ExportService, _render_html


@pytest.fixture
def sample_resume_content() -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(
                full_name="Jane Doe",
                email="jane.doe@example.com",
                phone="+1-555-0199",
                location="San Francisco, CA",
                headline="Senior Full Stack Engineer",
                linkedin="https://linkedin.com/in/janedoe",
                github="https://github.com/janedoe",
            ),
            summary="Experienced software engineer with experience in web applications.",
            skills=SkillCategory(
                technical=["Python", "FastAPI", "React", "PostgreSQL"],
                tools=["Docker", "Git"],
                languages=["English"],
            ),
            experience=[
                ExperienceItem(
                    id="exp-1",
                    role="Senior Software Engineer",
                    company="TechCorp Inc.",
                    location="San Francisco, CA",
                    start_date="2022-01",
                    current=True,
                    responsibilities=[
                        BulletItem(id="b-1", text="Responsible for developing backend APIs for client applications"),
                        BulletItem(id="b-2", text="Worked on optimizing database queries and fixing performance bugs"),
                    ],
                )
            ],
            projects=[
                ProjectItem(
                    id="proj-1",
                    name="CareerOS Platform",
                    description="Worked on building an AI-powered resume builder.",
                    technologies=["Python", "FastAPI", "React"],
                )
            ],
            education=[
                EducationItem(
                    id="edu-1",
                    institution="University of California, Berkeley",
                    degree="B.S.",
                    field="Computer Science",
                    start_date="2018",
                    end_date="2022",
                    gpa="3.8",
                )
            ],
        )
    )


@pytest.fixture
def sample_job_description() -> str:
    return """
    We are seeking a Senior Full Stack Engineer.
    Required skills: Python, FastAPI, Docker, Kubernetes, AWS, PostgreSQL, React.
    Responsibilities:
    - Architect and scale distributed microservices.
    - Optimize database queries and improve endpoint response times.
    - Deploy containerized applications using Docker and Kubernetes on AWS.
    """


def test_generate_summary_optimization(sample_resume_content, sample_job_description):
    service = OptimizationService()
    result = service.generate_summary_optimization(
        resume_content=sample_resume_content,
        job_description=sample_job_description,
        job_title="Senior Full Stack Engineer",
    )

    assert result.success is True
    assert len(result.suggestions) > 0

    sug = result.suggestions[0]
    assert sug["type"] == "professional_summary"
    assert sug["section"] == "summary"
    assert sug["entryId"] == "summary"
    assert sug["priority"] == "high"
    assert sug["action"] == "replace"
    assert "currentText" in sug
    assert "suggestedText" in sug
    assert len(sug["suggestedText"]) > len(sug["currentText"])
    assert "explanation" in sug
    assert "evidence" in sug
    assert "affectedKeywords" in sug


def test_generate_bullet_optimization(sample_resume_content, sample_job_description):
    service = OptimizationService()
    result = service.generate_bullet_optimization(
        resume_content=sample_resume_content,
        job_description=sample_job_description,
        section="experience",
    )

    assert result.success is True
    assert len(result.suggestions) >= 2

    for sug in result.suggestions:
        assert sug["type"] == "experience_bullet"
        assert sug["section"] == "experience"
        assert sug["entry_id"] == "exp-1"
        assert sug["child_id"] in ["b-1", "b-2"]
        assert sug["priority"] == "high"
        assert sug["action"] == "replace"
        assert "current_text" in sug
        assert "suggested_text" in sug
        assert "explanation" in sug
        assert "affected_keywords" in sug
        # Verify passive starters were eliminated
        assert not sug["suggested_text"].lower().startswith("responsible for")
        assert not sug["suggested_text"].lower().startswith("worked on")


def test_generate_skills_alignment(sample_resume_content, sample_job_description):
    service = OptimizationService()
    result = service.generate_skills_alignment(
        resume_content=sample_resume_content,
        job_description=sample_job_description,
    )

    assert result.success is True
    missing_suggestions = [s for s in result.suggestions if s.get("category") == "missing_from_resume"]
    assert len(missing_suggestions) > 0

    for sug in missing_suggestions:
        assert sug["type"] == "skills_alignment"
        assert sug["section"] == "skills"
        assert sug["action"] == "add"
        assert sug["priority"] == "medium"
        assert "skill" in sug
        assert "suggestedText" in sug
        assert "explanation" in sug
        assert f"Add '{sug['skill']}'" in sug["explanation"]


def test_validate_suggestion_passes_valid_summary_and_bullets(sample_resume_content):
    service = OptimizationService()

    summary_sug = {
        "type": "professional_summary",
        "section": "summary",
        "entryId": "summary",
        "currentText": sample_resume_content.profile.summary,
        "suggestedText": "Senior Full Stack Engineer with expertise in Python and FastAPI, driving scalable cloud systems.",
        "priority": "high",
        "action": "replace",
    }
    is_valid, err = service.validate_suggestion(summary_sug, sample_resume_content)
    assert is_valid is True

    bullet_sug = {
        "type": "experience_bullet",
        "section": "experience",
        "entry_id": "exp-1",
        "child_id": "b-1",
        "current_text": "Responsible for developing backend APIs",
        "suggested_text": "Architected and delivered high-performance backend APIs, reducing response times by 35%.",
        "priority": "high",
        "action": "replace",
    }
    is_valid, err = service.validate_suggestion(bullet_sug, sample_resume_content)
    assert is_valid is True

    skill_sug = {
        "type": "skills_alignment",
        "section": "skills",
        "category": "missing_from_resume",
        "skill": "Kubernetes",
        "suggestedText": "Kubernetes",
        "action": "add",
        "priority": "medium",
    }
    is_valid, err = service.validate_suggestion(skill_sug, sample_resume_content)
    assert is_valid is True


def test_optimize_resume_end_to_end(sample_resume_content, sample_job_description):
    service = OptimizationService()
    result = service.optimize_resume(
        resume_content=sample_resume_content,
        job_description=sample_job_description,
        job_title="Senior Full Stack Engineer",
    )

    assert result.success is True
    assert len(result.suggestions) > 0

    types = {s["type"] for s in result.suggestions}
    assert "professional_summary" in types
    assert "experience_bullet" in types
    assert "skills_alignment" in types


def test_apply_suggestion_to_content_skills(sample_resume_content):
    skill_sug = {
        "type": "skills_alignment",
        "section": "skills",
        "category": "missing_from_resume",
        "skill": "Kubernetes",
        "suggested_text": "Kubernetes",
        "action": "add",
    }
    updated = _apply_suggestion_to_content(sample_resume_content, skill_sug)
    assert "Kubernetes" in updated.profile.skills.technical

    # Ensure no duplicates when reapplied
    updated2 = _apply_suggestion_to_content(updated, skill_sug)
    assert updated2.profile.skills.technical.count("Kubernetes") == 1


def test_apply_suggestion_to_content_summary_and_bullet(sample_resume_content):
    summary_sug = {
        "type": "professional_summary",
        "section": "summary",
        "suggested_text": "Brand new tailored professional summary.",
    }
    updated = _apply_suggestion_to_content(sample_resume_content, summary_sug)
    assert updated.profile.summary == "Brand new tailored professional summary."

    bullet_sug = {
        "type": "experience_bullet",
        "section": "experience",
        "entry_id": "exp-1",
        "child_id": "b-1",
        "suggested_text": "Architected resilient backend APIs reducing latency by 40%.",
    }
    updated_bullet = _apply_suggestion_to_content(sample_resume_content, bullet_sug)
    exp = updated_bullet.profile.experience[0]
    matched_bullet = next(b for b in exp.responsibilities if b.id == "b-1")
    assert matched_bullet.text == "Architected resilient backend APIs reducing latency by 40%."


def test_export_service_render_and_pdf(sample_resume_content):
    export_svc = ExportService()
    html = _render_html(sample_resume_content)

    # Check that modern elements and bullet lists are rendered
    assert '<ul class="bullet-list">' in html
    assert "Jane Doe" in html
    assert "Senior Software Engineer" in html
    assert "Python" in html

    # Export PDF and verify non-empty byte buffer
    pdf_bytes = export_svc.export_pdf(sample_resume_content)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0
    assert pdf_bytes.startswith(b"%PDF")


def test_apply_version_operation_summary_and_skills_and_bullet(sample_resume_content):
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.service import AuthContext, AuthUser
    from app.dependencies import get_current_user
    from app.repositories.resume_repository import ResumeRepository

    user = AuthUser(id="test-user-1", email="test@example.com")
    auth_ctx = AuthContext(user=user, supabase=MagicMock(), jwt="fake-jwt")
    app.dependency_overrides[get_current_user] = lambda: auth_ctx

    client = TestClient(app)
    try:
        mock_version = {
            "id": "ver-123",
            "resume_id": "res-123",
            "version_name": "Test Version",
            "content": sample_resume_content.to_dict(),
            "created_at": "2026-09-04T12:00:00Z",
            "updated_at": "2026-09-04T12:00:00Z",
        }
        mock_resume = {"id": "res-123", "user_id": "test-user-1", "content": sample_resume_content.to_dict()}

        saved_contents = []

        def mock_update_version(vid, data):
            saved_contents.append(data.get("content"))
            return {**mock_version, "content": data.get("content"), "updated_at": "2026-09-04T12:01:00Z"}

        with patch.object(ResumeRepository, "get_version", return_value=mock_version), \
             patch.object(ResumeRepository, "get_resume", return_value=mock_resume), \
             patch.object(ResumeRepository, "update_version", side_effect=mock_update_version):

            # 1. Summary replace
            resp = client.post(
                "/api/resumes/versions/ver-123/apply-operation",
                json={
                    "operation": "replace",
                    "section": "summary",
                    "replacement": {"suggestedText": "Tailored executive summary."},
                },
            )
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["content"]["profile"]["summary"] == "Tailored executive summary."

            # 2. Skills insert
            resp = client.post(
                "/api/resumes/versions/ver-123/apply-operation",
                json={
                    "operation": "insert",
                    "section": "skills",
                    "replacement": {"skill": "Kubernetes, Terraform"},
                },
            )
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert "Kubernetes" in data["content"]["profile"]["skills"]["technical"]
            assert "Terraform" in data["content"]["profile"]["skills"]["technical"]

            # 3. Bullet replace with child_id
            resp = client.post(
                "/api/resumes/versions/ver-123/apply-operation",
                json={
                    "operation": "replace",
                    "section": "experience",
                    "target_id": "exp-1",
                    "child_id": "b-1",
                    "replacement": {"suggestedText": "Spearheaded microservices architecture reducing downtime by 50%."},
                },
            )
            assert resp.status_code == 200
            data = resp.json()["data"]
            exp = data["content"]["profile"]["experience"][0]
            b1 = next(b for b in exp["responsibilities"] if b["id"] == "b-1")
            assert b1["text"] == "Spearheaded microservices architecture reducing downtime by 50%."

    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_generate_optimizations_api_response_fields(sample_resume_content, sample_job_description):
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.service import AuthContext, AuthUser
    from app.dependencies import get_current_user
    from app.repositories.resume_repository import ResumeRepository
    from app.repositories.optimization_repository import OptimizationRepository

    user = AuthUser(id="test-user-1", email="test@example.com")
    auth_ctx = AuthContext(user=user, supabase=MagicMock(), jwt="fake-jwt")
    app.dependency_overrides[get_current_user] = lambda: auth_ctx

    client = TestClient(app)
    try:
        mock_resume = {"id": "res-123", "user_id": "test-user-1", "content": sample_resume_content.to_dict()}
        with patch.object(ResumeRepository, "get_resume", return_value=mock_resume), \
             patch.object(OptimizationRepository, "create_session", return_value={}), \
             patch.object(OptimizationRepository, "create_suggestion", return_value={}):

            resp = client.post(
                "/api/optimization/generate",
                json={
                    "resume_id": "res-123",
                    "job_description": sample_job_description,
                    "job_title": "Senior Full Stack Engineer",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "session_id" in data
            assert "suggestions" in data
            assert len(data["suggestions"]) > 0

            # Verify every suggestion has all required fields
            for sug in data["suggestions"]:
                assert "id" in sug
                assert "type" in sug
                assert "section" in sug
                assert "priority" in sug
                assert "action" in sug
                assert "status" in sug
                assert "explanation" in sug

    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_apply_version_operation_blocks_master_version(sample_resume_content):
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.service import AuthContext, AuthUser
    from app.dependencies import get_current_user
    from app.repositories.resume_repository import ResumeRepository

    user = AuthUser(id="test-user-1", email="test@example.com")
    auth_ctx = AuthContext(user=user, supabase=MagicMock(), jwt="fake-jwt")
    app.dependency_overrides[get_current_user] = lambda: auth_ctx

    client = TestClient(app)
    try:
        mock_master_version = {
            "id": "ver-master",
            "resume_id": "res-123",
            "version_name": "Master Resume",
            "is_master": True,
            "content": sample_resume_content.to_dict(),
            "created_at": "2026-09-04T12:00:00Z",
            "updated_at": "2026-09-04T12:00:00Z",
        }
        mock_resume = {"id": "res-123", "user_id": "test-user-1", "content": sample_resume_content.to_dict()}

        with patch.object(ResumeRepository, "get_version", return_value=mock_master_version), \
             patch.object(ResumeRepository, "get_resume", return_value=mock_resume):

            resp = client.post(
                "/api/resumes/versions/ver-master/apply-operation",
                json={
                    "operation": "replace",
                    "section": "summary",
                    "replacement": {"suggestedText": "Should fail on master."},
                },
            )
            assert resp.status_code == 400
            err_msg = resp.json().get("error", {}).get("message", "")
            assert "Cannot modify master version directly" in err_msg

    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_accept_suggestion_does_not_mutate_master_resume(sample_resume_content):
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.service import AuthContext, AuthUser
    from app.dependencies import get_current_user
    from app.api.routes.optimization import get_auth_token
    from app.repositories.resume_repository import ResumeRepository
    from app.repositories.optimization_repository import OptimizationRepository

    user = AuthUser(id="test-user-1", email="test@example.com")
    auth_ctx = AuthContext(user=user, supabase=MagicMock(), jwt="fake-jwt")
    app.dependency_overrides[get_current_user] = lambda: auth_ctx
    app.dependency_overrides[get_auth_token] = lambda: "fake-jwt"

    client = TestClient(app)
    try:
        mock_resume = {"id": "res-123", "user_id": "test-user-1", "content": sample_resume_content.to_dict()}
        mock_session = {"id": "sess-123", "resume_id": "res-123", "version_id": None}
        mock_suggestion_rec = {
            "id": "sug-1",
            "session_id": "sess-123",
            "suggestion": {
                "id": "sug-1",
                "type": "summary_tailoring",
                "section": "summary",
                "suggested_text": "Tailored master test",
            },
        }

        mock_update_resume = MagicMock()
        mock_update_sug = MagicMock()
        mock_update_sess = MagicMock()

        with patch.object(OptimizationRepository, "get_suggestion", return_value=mock_suggestion_rec), \
             patch.object(OptimizationRepository, "get_session", return_value=mock_session), \
             patch.object(ResumeRepository, "get_resume", return_value=mock_resume), \
             patch.object(ResumeRepository, "update_resume", mock_update_resume), \
             patch.object(OptimizationRepository, "update_suggestion", mock_update_sug), \
             patch.object(OptimizationRepository, "list_suggestions_for_session", return_value=[mock_suggestion_rec]), \
             patch.object(OptimizationRepository, "update_session", mock_update_sess):

            resp = client.post(
                "/api/optimization/suggestions/accept",
                json={"session_id": "sess-123", "suggestion_id": "sug-1"},
            )
            # Master-immutability contract: accepting a suggestion with no derived
            # version must FAIL truthfully (400), never report fake success while
            # producing no real document artifact.
            assert resp.status_code == 400
            err_msg = (resp.json().get("error") or {}).get("message", "") or resp.json().get("detail", "")
            assert "immutable" in err_msg.lower() or "derived version" in err_msg.lower()
            # Invariant: Master resume must NOT be modified
            mock_update_resume.assert_not_called()
            # Invariant: the suggestion must NOT be marked accepted/applied
            mock_update_sug.assert_not_called()
            mock_update_sess.assert_not_called()

    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_auth_token, None)


