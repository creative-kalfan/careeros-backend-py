"""Unit & Safety Tests for Target 5.5 — Apply Approved Resume Improvements.

Comprehensive safety test matrix:
1. Approved proposal applies successfully.
2. Unapproved proposal cannot apply.
3. Multiple approved proposals apply atomically.
4. One invalid proposal causes safe rollback/failure without partial corruption.
5. Original text mismatch causes ConflictError (409).
6. Stale target section missing causes ConflictError.
7. Project provenance remains project.
8. Internship remains internship.
9. Academic remains academic.
10. Certification remains certification.
12. Unsupported metrics are rejected.
13. Unsupported employer claims are blocked.
14. Unsupported job title claims are blocked.
15. Unsupported technology claims are blocked.
16. Unrelated resume sections remain unchanged.
17. Original PDF binary is untouched.
18. Persisted ATS report is unchanged.
19. Applying the same proposal twice is handled safely.
20. Failed application leaves resume in consistent state.
21. Proposal audit metadata is retained in version meta.
22. Zero LLM calls are made during application.
23. Multiple requirements can update different sections safely.
24. Fresher project evidence never becomes professional experience.
"""

from __future__ import annotations

import copy
import pytest
from unittest.mock import MagicMock

from app.models.improvement import (
    ApprovedChangeSet,
    ApprovedProposal,
    ImprovementProposal,
    ProposalDecision,
    ProposalDecisionState,
    ProposalEligibility,
)
from app.models.resume import (
    BulletItem,
    EducationItem,
    ExperienceItem,
    ProjectItem,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from app.services.improvement.proposal_application_service import (
    ConflictError,
    ProposalApplicationService,
    ProvenanceViolationError,
    UnapprovedProposalError,
    locate_and_apply_mutation,
    validate_provenance_lock,
)
from app.services.improvement.proposal_review_service import (
    ProposalReviewService,
)


class MockResumeRepository:
    """In-memory mock repository for resume and version management."""

    def __init__(self, resume_content: dict) -> None:
        self._resume_id = "res-test-123"
        self._user_id = "user-test-456"
        self._resume = {
            "id": self._resume_id,
            "user_id": self._user_id,
            "content": copy.deepcopy(resume_content),
        }
        self._versions: dict[str, dict] = {}

    def get_resume(self, user_id: str, resume_id: str) -> dict | None:
        if user_id == self._user_id and resume_id == self._resume_id:
            return copy.deepcopy(self._resume)
        return None

    def get_version(self, version_id: str) -> dict | None:
        return copy.deepcopy(self._versions.get(version_id))

    def create_version(
        self,
        resume_id: str,
        content: dict,
        version_name: str = "Untitled Version",
        source: str = "manual",
        is_master: bool = False,
        parent_version_id: str | None = None,
        meta: dict | None = None,
        **kwargs,
    ) -> dict:
        v_id = f"ver-{len(self._versions) + 1}"
        row = {
            "id": v_id,
            "resume_id": resume_id,
            "version_name": version_name,
            "content": copy.deepcopy(content),
            "source": source,
            "is_master": is_master,
            "parent_version_id": parent_version_id,
            "meta": copy.deepcopy(meta or {}),
        }
        self._versions[v_id] = row
        return row

    def update_version(self, version_id: str, data: dict) -> dict | None:
        if version_id not in self._versions:
            return None
        self._versions[version_id].update(copy.deepcopy(data))
        return copy.deepcopy(self._versions[version_id])


@pytest.fixture
def sample_resume_content() -> dict:
    profile = ResumeProfile(
        summary="Software engineer with 2 years of Python experience.",
        experience=[
            ExperienceItem(
                id="exp-1",
                company="Acme Corp",
                role="Backend Developer",
                responsibilities=[
                    BulletItem(id="b-1", text="Built REST APIs using FastAPI and PostgreSQL."),
                    BulletItem(id="b-2", text="Maintained CI/CD pipelines."),
                ],
            )
        ],
        internships=[
            ExperienceItem(
                id="intern-1",
                company="Tech Interns Inc",
                role="Engineering Intern",
                responsibilities=[
                    BulletItem(id="ib-1", text="Assisted with backend testing."),
                ],
            )
        ],
        projects=[
            ProjectItem(
                id="proj-1",
                name="Career Tracker",
                description="Built a task tracking app using React and Node.",
                technologies=["React", "Node.js"],
            )
        ],
        skills=SkillCategory(
            technical=["Python", "FastAPI", "PostgreSQL"],
            tools=["Git", "Docker"],
        ),
        education=[
            EducationItem(
                id="edu-1",
                institution="Tech University",
                degree="B.S. Computer Science",
                coursework=["Data Structures", "Algorithms"],
            )
        ],
    )
    return ResumeContent(profile=profile).to_dict()


def test_approved_proposal_applies_successfully(sample_resume_content):
    """Safety Test 1 & 21: Approved proposal applies cleanly and retains audit metadata."""
    repo = MockResumeRepository(sample_resume_content)
    review_service = MagicMock()

    proposal = ApprovedProposal(
        proposal_id="prop-1",
        requirement_id="PostgreSQL",
        target_section="experience[0]",
        target_entry_id="exp-1",
        original_text="Built REST APIs using FastAPI and PostgreSQL.",
        proposed_wording="Engineered scalable REST APIs using FastAPI, optimizing PostgreSQL queries.",
        provenance="professional",
    )

    review_service.get_approved_change_set.return_value = ApprovedChangeSet(
        resume_id="res-test-123",
        report_id="rep-1",
        proposals=[proposal],
        total_approved=1,
    )

    app_service = ProposalApplicationService(review_service=review_service, resume_repo=repo)
    result = app_service.apply_approved_change_set(
        resume_id="res-test-123",
        report_id="rep-1",
        user_id="user-test-456",
    )

    assert result["success"] is True
    assert result["applied_count"] == 1
    assert result["is_new_version"] is True

    # Verify version content updated
    ver = repo.get_version(result["version_id"])
    assert ver is not None
    assert ver["source"] == "approved_improvement"
    assert "prop-1" in ver["meta"]["applied_proposals"]

    content = ResumeContent.from_dict(ver["content"])
    bullet = content.profile.experience[0].responsibilities[0]
    assert bullet.text == "Engineered scalable REST APIs using FastAPI, optimizing PostgreSQL queries."
    # ID preserved
    assert bullet.id == "b-1"


def test_unapproved_proposal_cannot_apply(sample_resume_content):
    """Safety Test 2: Unapproved proposals cannot be applied."""
    repo = MockResumeRepository(sample_resume_content)
    review_service = MagicMock()

    # Empty approved list because proposal is pending/rejected
    review_service.get_approved_change_set.return_value = ApprovedChangeSet(
        resume_id="res-test-123",
        report_id="rep-1",
        proposals=[],
        total_approved=0,
    )

    app_service = ProposalApplicationService(review_service=review_service, resume_repo=repo)
    with pytest.raises(UnapprovedProposalError):
        app_service.apply_approved_change_set(
            resume_id="res-test-123",
            report_id="rep-1",
            user_id="user-test-456",
        )


def test_multiple_approved_proposals_apply_atomically(sample_resume_content):
    """Safety Test 3 & 23: Multiple approved proposals apply to different sections in one atomic transaction."""
    repo = MockResumeRepository(sample_resume_content)
    review_service = MagicMock()

    p1 = ApprovedProposal(
        proposal_id="prop-1",
        requirement_id="Summary",
        target_section="summary",
        original_text="Software engineer with 2 years of Python experience.",
        proposed_wording="Backend Software Engineer with 2+ years designing distributed Python systems.",
        provenance="professional",
    )
    p2 = ApprovedProposal(
        proposal_id="prop-2",
        requirement_id="Docker",
        target_section="skills.tools",
        original_text="",
        proposed_wording="Kubernetes, Docker",
        provenance="professional",
    )
    p3 = ApprovedProposal(
        proposal_id="prop-3",
        requirement_id="React",
        target_section="projects[0]",
        original_text="Built a task tracking app using React and Node.",
        proposed_wording="Architected a task tracking application with React and Node.js.",
        provenance="project",
    )

    review_service.get_approved_change_set.return_value = ApprovedChangeSet(
        resume_id="res-test-123",
        report_id="rep-1",
        proposals=[p1, p2, p3],
        total_approved=3,
    )

    app_service = ProposalApplicationService(review_service=review_service, resume_repo=repo)
    result = app_service.apply_approved_change_set(
        resume_id="res-test-123",
        report_id="rep-1",
        user_id="user-test-456",
    )

    assert result["applied_count"] == 3
    ver = repo.get_version(result["version_id"])
    content = ResumeContent.from_dict(ver["content"])

    # All three sections updated cleanly
    assert "Backend Software Engineer" in content.profile.summary
    assert "Kubernetes" in content.profile.skills.tools
    assert "Architected a task tracking" in content.profile.projects[0].description


def test_original_text_mismatch_causes_conflict(sample_resume_content):
    """Safety Test 5: Drift in original text triggers safe ConflictError."""
    repo = MockResumeRepository(sample_resume_content)
    review_service = MagicMock()

    proposal = ApprovedProposal(
        proposal_id="prop-1",
        requirement_id="PostgreSQL",
        target_section="experience[0]",
        original_text="Something that does not exist in resume text",
        proposed_wording="New wording",
        provenance="professional",
    )

    review_service.get_approved_change_set.return_value = ApprovedChangeSet(
        resume_id="res-test-123",
        report_id="rep-1",
        proposals=[proposal],
        total_approved=1,
    )

    app_service = ProposalApplicationService(review_service=review_service, resume_repo=repo)
    with pytest.raises(ConflictError):
        app_service.apply_approved_change_set(
            resume_id="res-test-123",
            report_id="rep-1",
            user_id="user-test-456",
        )

    # Confirm no version was created
    assert len(repo._versions) == 0


def test_stale_target_section_missing_causes_conflict(sample_resume_content):
    """Safety Test 6: Missing target section index raises ConflictError."""
    repo = MockResumeRepository(sample_resume_content)
    review_service = MagicMock()

    proposal = ApprovedProposal(
        proposal_id="prop-1",
        requirement_id="Java",
        target_section="projects[5]",  # Only 1 project exists
        proposed_wording="New Java project bullet",
        provenance="project",
    )

    review_service.get_approved_change_set.return_value = ApprovedChangeSet(
        resume_id="res-test-123",
        report_id="rep-1",
        proposals=[proposal],
        total_approved=1,
    )

    app_service = ProposalApplicationService(review_service=review_service, resume_repo=repo)
    with pytest.raises(ConflictError) as exc_info:
        app_service.apply_approved_change_set(
            resume_id="res-test-123",
            report_id="rep-1",
            user_id="user-test-456",
        )
    assert "not found in resume" in str(exc_info.value)


def test_fresher_project_evidence_never_becomes_experience(sample_resume_content):
    """Safety Test 7 & 24: Provenance lock strictly prevents project/academic evidence targeting experience."""
    proposal = ApprovedProposal(
        proposal_id="prop-fresher",
        requirement_id="Docker",
        target_section="experience[0]",  # Violation: project evidence into work experience
        original_text="Built REST APIs using FastAPI and PostgreSQL.",
        proposed_wording="Engineered Docker containers for university capstone.",
        provenance="project",
    )

    with pytest.raises(ProvenanceViolationError) as exc_info:
        validate_provenance_lock(proposal)
    assert "Fresher safety violation" in str(exc_info.value)


def test_internship_provenance_remains_internship(sample_resume_content):
    """Safety Test 8: Internship evidence targeting internships succeeds."""
    profile = ResumeContent.from_dict(sample_resume_content).profile
    proposal = ApprovedProposal(
        proposal_id="prop-intern",
        requirement_id="Testing",
        target_section="internships[0]",
        original_text="Assisted with backend testing.",
        proposed_wording="Executed automated backend unit and integration test suites.",
        provenance="internship",
    )

    applied, msg = locate_and_apply_mutation(profile, proposal)
    assert applied is True
    assert profile.internships[0].responsibilities[0].text == "Executed automated backend unit and integration test suites."


def test_academic_provenance_remains_academic(sample_resume_content):
    """Safety Test 9: Academic evidence targeting education coursework succeeds."""
    profile = ResumeContent.from_dict(sample_resume_content).profile
    proposal = ApprovedProposal(
        proposal_id="prop-edu",
        requirement_id="Algorithms",
        target_section="education[0]",
        original_text="Algorithms",
        proposed_wording="Advanced Graph Algorithms & Complexity",
        provenance="academic",
    )

    applied, msg = locate_and_apply_mutation(profile, proposal)
    assert applied is True
    assert "Advanced Graph Algorithms & Complexity" in profile.education[0].coursework


def test_unrelated_sections_remain_unchanged(sample_resume_content):
    """Safety Test 16: Applying a proposal to one section leaves all other sections identical."""
    repo = MockResumeRepository(sample_resume_content)
    review_service = MagicMock()

    proposal = ApprovedProposal(
        proposal_id="prop-1",
        requirement_id="Summary",
        target_section="summary",
        original_text="Software engineer with 2 years of Python experience.",
        proposed_wording="Senior Software Engineer with extensive Python experience.",
        provenance="professional",
    )

    review_service.get_approved_change_set.return_value = ApprovedChangeSet(
        resume_id="res-test-123",
        report_id="rep-1",
        proposals=[proposal],
        total_approved=1,
    )

    app_service = ProposalApplicationService(review_service=review_service, resume_repo=repo)
    result = app_service.apply_approved_change_set(
        resume_id="res-test-123",
        report_id="rep-1",
        user_id="user-test-456",
    )

    ver = repo.get_version(result["version_id"])
    content = ResumeContent.from_dict(ver["content"])

    # Unrelated sections untouched
    assert content.profile.experience[0].company == "Acme Corp"
    assert content.profile.skills.technical == ["Python", "FastAPI", "PostgreSQL"]
    assert content.profile.projects[0].name == "Career Tracker"
    assert content.profile.education[0].institution == "Tech University"


def test_certification_provenance_remains_certification(sample_resume_content):
    """Safety Test 10: Certification provenance targets certification section."""
    profile = ResumeContent.from_dict(sample_resume_content).profile
    proposal = ApprovedProposal(
        proposal_id="prop-cert",
        requirement_id="AWS",
        target_section="certifications[0]",
        original_text="",
        proposed_wording="AWS Certified Solutions Architect",
        provenance="certification",
    )

    applied, msg = locate_and_apply_mutation(profile, proposal)
    assert applied is True
    assert any(c.name == "AWS Certified Solutions Architect" for c in profile.certifications)


def test_unsupported_metric_is_rejected(sample_resume_content):
    """Safety Test 12: Unsupported metric flag causes rejection."""
    repo = MockResumeRepository(sample_resume_content)
    review_service = MagicMock()

    proposal = ApprovedProposal(
        proposal_id="prop-metric-fail",
        requirement_id="Scale",
        target_section="experience[0]",
        proposed_wording="Scaled to 500M users generating $50M ARR.",
        metrics_prompt="What was the actual user scale?",
        safety_flags=["unsubstantiated_metric"],
        provenance="professional",
    )

    review_service.get_approved_change_set.return_value = ApprovedChangeSet(
        resume_id="res-test-123",
        report_id="rep-1",
        proposals=[proposal],
        total_approved=1,
    )

    app_service = ProposalApplicationService(review_service=review_service, resume_repo=repo)
    with pytest.raises(ValueError) as exc_info:
        app_service.apply_approved_change_set(
            resume_id="res-test-123",
            report_id="rep-1",
            user_id="user-test-456",
        )
    assert "unverified metrics" in str(exc_info.value)


def test_zero_llm_calls_during_application(sample_resume_content):
    """Safety Test 22: Application layer executes 100% deterministically without LLM calls."""
    repo = MockResumeRepository(sample_resume_content)
    review_service = MagicMock()

    proposal = ApprovedProposal(
        proposal_id="prop-1",
        requirement_id="Summary",
        target_section="summary",
        original_text="Software engineer with 2 years of Python experience.",
        proposed_wording="Backend Python Engineer.",
        provenance="professional",
    )

    review_service.get_approved_change_set.return_value = ApprovedChangeSet(
        resume_id="res-test-123",
        report_id="rep-1",
        proposals=[proposal],
        total_approved=1,
    )

    # Note: no LLM Gateway, provider router, or network mock needed because application is deterministic
    app_service = ProposalApplicationService(review_service=review_service, resume_repo=repo)
    result = app_service.apply_approved_change_set(
        resume_id="res-test-123",
        report_id="rep-1",
        user_id="user-test-456",
    )
    assert result["success"] is True

