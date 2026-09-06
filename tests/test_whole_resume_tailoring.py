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


def test_tailoring_preserves_identity_and_non_tailorable_sections() -> None:
    content = sample_resume_content()
    content.profile.education = []
    candidate = {
        "summary": "Python engineer. Python engineer.",
        "experience": [],
        "education": [{"degree": "Discarded by guard"}],
    }

    preserved = whole_resume_tailoring_service._preserve_profile_sections(
        content.profile,
        candidate,
    )

    assert preserved["personal"]["full_name"] == "Jane Doe"
    assert len(preserved["experience"]) == 1
    assert preserved["education"] == []
    assert whole_resume_tailoring_service._is_safe_rewrite("Candidate") is False
    assert whole_resume_tailoring_service._is_safe_rewrite("Python engineer. Python engineer.") is False


def test_whole_resume_tailoring_experience_without_role_does_not_crash() -> None:
    """Regression: a resume whose experience entry has an unparsed role (None).

    Previously crashed with `AttributeError: 'NoneType' object has no attribute
    'lower'` from the deterministic tailoring pass calling `exp.role.lower()`.
    """
    content = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Kavya Raman", email="kavya@example.com"),
            summary="Finance professional handling client accounting and reconciliations.",
            skills=SkillCategory(
                technical=["Accounting", "Excel", "Reconciliation"],
                tools=["SAP"],
                soft_skills=["Communication"],
            ),
            experience=[
                ExperienceItem(
                    company="ZS Associates",
                    role=None,  # parser did not extract the job title
                    start_date="2022-01",
                    responsibilities=[
                        BulletItem(text="Prepared monthly client account reconciliations."),
                    ],
                    tools=["Excel", "SAP"],
                )
            ],
            education=[],
        )
    )
    jd = (
        "Finance Associate - Client Accounting\n"
        "Requirements:\n"
        "- Strong knowledge of accounting\n"
        "- Proficiency in Excel and financial reporting\n"
        "- Client reconciliation experience\n"
    )

    result = whole_resume_tailoring_service.tailor_resume(
        resume_content=content,
        job_description=jd,
        job_title="Finance Associate",
        company="ZS Associates",
    )

    assert isinstance(result, TailorResumeResponse)
    assert result.success is True
    assert result.score_comparison is not None
    assert result.tailored_profile.get("summary")
    assert result.tailored_profile["experience"][0]["company"] == "ZS Associates"
    assert result.tailored_profile["experience"][0]["role"] is None


def test_whole_resume_tailoring_sparse_resume_minimal_jd() -> None:
    """Sparse resume with minimal JD: genuinely empty optional fields must not crash."""
    content = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Aarav Patel"),
            summary=None,
            skills=SkillCategory(),
            experience=[],
            education=[],
        )
    )
    jd = "Finance Associate: handle client accounting."

    result = whole_resume_tailoring_service.tailor_resume(
        resume_content=content,
        job_description=jd,
        job_title="Finance Associate",
    )

    assert isinstance(result, TailorResumeResponse)
    assert result.success is True
    assert result.score_comparison is not None
    assert result.score_comparison.baseline_score >= 0
    assert result.score_comparison.tailored_score >= 0


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
             patch.object(ResumeRepository, "create_version", return_value=mock_created_ver) as mock_create, \
             patch.object(ResumeRepository, "update_version", return_value=mock_created_ver) as mock_update, \
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
            assert mock_create.call_args.kwargs["source"] == "tailoring"
            update_payload = mock_update.call_args.args[1]
            assert "source" not in update_payload
            assert update_payload["meta"]["compilation_strategy"] == "document_compiler"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_numeric_fabrication_guard_catches_unsupported_metrics() -> None:
    from app.services.optimization.numeric_guard import numeric_guard

    content = sample_resume_content()
    source_profile = content.profile

    # Tailored profile injecting fabricated numbers (e.g. 99.9%, $5M, 50+)
    tailored_dict = source_profile.to_dict()
    tailored_dict["summary"] = "Experienced engineer driving 99.9% uptime and managing $5M budget."
    tailored_dict["experience"][0]["responsibilities"][0]["text"] = "Managed 50+ engineers across 10 teams."

    audited, issues = numeric_guard.audit_tailored_profile(
        source_profile=source_profile,
        tailored_profile_dict=tailored_dict,
    )

    assert len(issues) >= 2
    assert any("99.9%" in i or "5m" in i for i in issues)
    assert any("50+" in i for i in issues)


def test_tailoring_noc_analyst_to_finance_associate_transferable() -> None:
    from app.services.optimization.semantic_guard import semantic_guard

    content = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(
                full_name="Alex Chen",
                email="alex.chen@example.com",
                phone="+15551234567",
                location="Chicago, IL",
            ),
            summary="Network Operations Center (NOC) Analyst with 4 years managing enterprise systems, following SOP guidelines, and generating operational reports.",
            skills=SkillCategory(
                technical=["Network Monitoring", "Linux", "SOP Adherence", "Incident Management", "Process Documentation"],
                tools=["Wireshark", "JIRA", "Pingdom"],
                soft_skills=["Cross-Functional Collaboration", "Operational Reporting", "Problem Solving"],
            ),
            experience=[
                ExperienceItem(
                    company="CloudTech Global",
                    role="NOC Analyst",
                    start_date="2020-06",
                    end_date="2024-06",
                    responsibilities=[
                        BulletItem(text="Maintained rigorous SOP adherence and operational documentation for all incident workflows."),
                        BulletItem(text="Generated weekly operational reporting and metrics for leadership reviews."),
                        BulletItem(text="Fostered cross-functional collaboration between engineering and support teams to resolve issues."),
                    ],
                    tools=["JIRA", "Linux"],
                )
            ],
            education=[],
        )
    )

    zs_jd = (
        "ZS Associates - Finance Associate\n\n"
        "What You'll Do:\n"
        "• Execute billing and client invoicing operations in SAP ERP.\n"
        "• Perform monthly account reconciliation and contract-to-cash workflows.\n"
        "• Maintain strict SOP adherence and comprehensive audit trail & documentation for all financial transactions.\n"
        "• Prepare weekly operational reporting & metrics on billing status and revenue recognition.\n"
        "• Drive cross-functional collaboration with client teams and corporate accounting.\n\n"
        "What You'll Bring:\n"
        "• Bachelor's degree in Finance, Accounting, or related field.\n"
        "• Proficiency in SAP ERP and Microsoft Excel.\n"
        "• Commitment to process compliance & governance and operational discipline.\n"
    )

    result = whole_resume_tailoring_service.tailor_resume(
        resume_content=content,
        job_description=zs_jd,
        job_title="Finance Associate",
        company="ZS Associates",
    )

    assert isinstance(result, TailorResumeResponse)
    assert result.success is True
    assert result.limited_alignment is False

    # Verify diff: summary reframed
    orig_summary = content.profile.summary
    tailored_summary = result.tailored_profile.get("summary")
    assert tailored_summary is not None
    assert tailored_summary != orig_summary
    assert (
        "SOP adherence" in tailored_summary
        or "operational documentation" in tailored_summary
        or "cross-functional collaboration" in tailored_summary
    )
    assert "Finance Associate" in tailored_summary

    # Verify diff: skills reordered with transferable overlapping skills prioritized
    orig_tech = content.profile.skills.technical
    tailored_tech = result.tailored_profile.get("skills", {}).get("technical", [])
    assert tailored_tech != orig_tech
    assert tailored_tech[0] in ["SOP Adherence", "Process Documentation"]

    # Verify SemanticFabricationGuard passes with 0 issues
    audited, issues = semantic_guard.audit_tailored_profile(
        source_profile=content.profile,
        tailored_profile_dict=result.tailored_profile,
    )
    assert len(issues) == 0, f"SemanticFabricationGuard found issues: {issues}"


def test_tailoring_genuine_zero_overlap_returns_limited_alignment() -> None:
    content = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(
                full_name="Pastry Chef Gordon",
                email="gordon@example.com",
            ),
            summary="Artisanal Pastry Chef with 10 years experience in French patisserie and sourdough fermentation.",
            skills=SkillCategory(
                technical=["Baking", "Pastry Arts", "Sourdough Fermentation", "Recipe Formulation"],
                tools=["Convection Oven", "Proofer"],
            ),
            experience=[
                ExperienceItem(
                    company="Le Petit Bistro",
                    role="Head Pastry Chef",
                    start_date="2018-01",
                    responsibilities=[
                        BulletItem(text="Baked 500+ artisanal loaves and pastries daily for breakfast service."),
                        BulletItem(text="Managed kitchen pantry inventory and ingredient sourcing."),
                    ],
                )
            ],
            education=[],
        )
    )

    tech_jd = (
        "Lead Python Developer - Cloud Infrastructure\n\n"
        "Requirements:\n"
        "• 5+ years building microservices with Python and FastAPI.\n"
        "• Deep hands-on experience with PostgreSQL, Docker, and Kubernetes.\n"
        "• Strong background in distributed systems and cloud architecture.\n"
    )

    result = whole_resume_tailoring_service.tailor_resume(
        resume_content=content,
        job_description=tech_jd,
        job_title="Lead Python Developer",
        company="CloudScale Inc",
    )

    assert isinstance(result, TailorResumeResponse)
    assert result.success is True
    assert result.limited_alignment is True
    assert result.alignment_message == "Limited alignment found; consider whether this resume is a strong fit for this role."
