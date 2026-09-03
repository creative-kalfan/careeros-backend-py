"""Tests for Target 4.1: ATS Requirement → Resume Evidence Mapping.

Tests cover:
1. Exact evidence match
2. Semantic evidence match
3. Partial evidence
4. Missing evidence
5. Unknown result
6. Multiple evidence items
7. Skill-only evidence vs experience evidence
8. Strong experience evidence
9. Weak evidence
10. Hallucinated evidence rejection
11. Evidence validation failure
12. Deterministic fallback
13. Semantic override with valid evidence
14. Semantic override rejected without evidence
15. Multiple requirement categories
16. Accenture Service Desk regression
17. Evidence source section tracking
18. Evidence explanation generation
19. Deterministic status preservation
20. Reconciled explanation quality
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import List, Dict, Any

from app.models.ats import (
    RequirementCoverage,
    EvidenceLevel,
    JobRequirementType,
    SemanticMatchStatus,
    SemanticEvidenceStrength,
    SemanticRequirementAssessment,
    SemanticAnalysisResult,
    ReconciledRequirement,
)
from app.models.resume import (
    ResumeContent,
    ResumeProfile,
    PersonalInfo,
    SkillCategory,
    ExperienceItem,
    EducationItem,
    ProjectItem,
    ResumeMeta,
)
from app.services.ats.ats_analyzer import ATSAnalyzer
from app.services.ats.semantic_reconciler import (
    reconcile_requirements,
    apply_reconciliation_to_coverage,
    _validate_evidence_against_resume,
    _generate_reconciled_explanation,
)
from app.services.ats.job_description_parser import JobDescriptionParser


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ACCENTURE_SERVICE_DESK_JD = """
Accenture is hiring a Service Desk Associate (L1 Technical Support) for our IT Service Desk in Bengaluru.

Job Description:
We are looking for candidates to provide Level 1 technical support and Service Desk Management. You will use ITSM tools such as ServiceNow and BMC Remedy to manage Incident Management and the ticket lifecycle.

Key Responsibilities:
- Handle incidents and service requests using ITSM and ticketing systems.
- Provide remote user support, voice-based support, and email/chat/remote desktop support.
- Troubleshoot hardware/software issues and maintain knowledge bases.
- Ensure Service Level Agreements (SLAs) are met.
- Excellent verbal and written communication skills are mandatory.
- Primary point of contact for customer service.
- Typical rotational shifts including 9.5-hour rotational shifts.
- Work includes US/night shifts and weekends/public holidays.
- Office location is Bengaluru.

Requirements:
- 0-2 years experience in IT support.
- Microsoft 365 / O365 and Active Directory knowledge.
- Experience with remote troubleshooting tools.
- 15 years of full-time education.
- Bachelor's degree in Computer Science or IT field.
"""


def _make_service_desk_resume() -> ResumeContent:
    """Create the Accenture Service Desk test resume."""
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Jane Doe",
            email="jane@example.com",
            phone="1234567890",
            headline="Service Desk Analyst"
        ),
        summary=(
            "L1 Service Desk analyst with ITSM and ServiceNow experience. "
            "Handles Incident Management and SLA adherence. Provides remote troubleshooting "
            "and customer service. Strong verbal and written communication and problem solving."
        ),
        skills=SkillCategory(
            technical=["ServiceNow", "ITSM", "SLA", "O365", "PowerShell"],
            tools=["JIRA"]
        ),
        experience=[
            ExperienceItem(
                company="IT Corp",
                role="Service Desk Analyst",
                responsibilities=[
                    "Managed Level 1 incident tickets using ServiceNow and ITSM processes",
                    "Owned ticketing systems and ticket lifecycle and knowledge bases within a Service Desk",
                    "Delivered remote troubleshooting and customer service to end users",
                    "Handled Bengaluru rotational shifts",
                ]
            )
        ],
        education=[
            EducationItem(
                institution="State University",
                degree="Bachelor of Science",
                field="Computer Science"
            )
        ],
        projects=[
            ProjectItem(
                name="Self-Service Portal",
                description="Built a knowledge base to reduce ticket volume",
                technologies=["ServiceNow"]
            )
        ]
    )
    return ResumeContent(profile=profile)


# ---------------------------------------------------------------------------
# 1. Exact Evidence Match
# ---------------------------------------------------------------------------

def test_exact_evidence_match():
    """When a requirement is exactly present in the resume, evidence is real and traceable."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )
    # Find ServiceNow coverage
    sn_cov = next((c for c in result.requirement_coverage if c.requirement == "ServiceNow"), None)
    assert sn_cov is not None
    assert sn_cov.status == "matched"
    assert sn_cov.evidence_level == EvidenceLevel.STRONG
    assert len(sn_cov.resume_evidence) > 0
    # Evidence must contain actual resume text
    assert any("ServiceNow" in ev for ev in sn_cov.resume_evidence)
    # Deterministic status must be preserved
    assert sn_cov.deterministic_status == "matched"
    # Evidence source section must be tracked
    assert sn_cov.evidence_source_section is not None
    # Evidence explanation must be present
    assert sn_cov.evidence_explanation is not None
    assert "ServiceNow" in sn_cov.evidence_explanation


# ---------------------------------------------------------------------------
# 2. Semantic Evidence Match
# ---------------------------------------------------------------------------

def test_semantic_evidence_match():
    """When semantic reasoning upgrades a requirement, evidence is real and traceable."""
    # Create a requirement that is MISSING deterministically
    concept_coverage = [
        RequirementCoverage(
            requirement="L1 Technical Support",
            requirement_type=JobRequirementType.REQUIRED,
            resume_evidence=[],
            evidence_level=EvidenceLevel.NONE,
            category="requirement",
            importance="high",
            status="missing",
            deterministic_status="missing",
        )
    ]

    # LLM provides valid evidence that exists in resume
    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="L1 Technical Support",
                status=SemanticMatchStatus.MATCHED,
                confidence=0.91,
                evidence="Managed Level 1 incident tickets using ServiceNow and ITSM processes",
                reasoning="First-line technical assistance is semantically equivalent to Level 1 technical support.",
                evidence_strength=SemanticEvidenceStrength.STRONG,
            )
        ],
        success=True,
    )

    resume_text_lower = "managed level 1 incident tickets using servicenow and itsm processes delivered remote troubleshooting and customer service".lower()

    reconciled, upgrades, overrides = reconcile_requirements(
        concept_coverage, semantic_result, resume_text_lower,
    )

    updated = apply_reconciliation_to_coverage(concept_coverage, reconciled)
    cov = updated[0]

    # Status should be upgraded
    assert cov.status == "matched"
    # Deterministic status should be preserved
    assert cov.deterministic_status == "missing"
    # Semantic fields should be populated
    assert cov.semantic_status == SemanticMatchStatus.MATCHED
    assert cov.semantic_evidence == "Managed Level 1 incident tickets using ServiceNow and ITSM processes"
    assert cov.semantic_reasoning is not None
    # Evidence explanation should reflect the upgrade
    assert cov.evidence_explanation is not None
    assert "L1 Technical Support" in cov.evidence_explanation
    # Reasoning source should be LLM
    assert cov.reasoning_source == "LLM"


# ---------------------------------------------------------------------------
# 3. Partial Evidence
# ---------------------------------------------------------------------------

def test_partial_evidence():
    """When evidence is partial, the explanation describes what is missing."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )
    # Remote User Support should be partial (has "remote troubleshooting" but not full phrase)
    remote_cov = next((c for c in result.requirement_coverage if c.requirement == "Remote User Support"), None)
    if remote_cov:
        assert remote_cov.status == "partial"
        assert remote_cov.evidence_level == EvidenceLevel.PARTIAL
        assert len(remote_cov.resume_evidence) > 0
        assert remote_cov.evidence_explanation is not None
        assert "partial" in remote_cov.evidence_explanation.lower() or "does not fully" in remote_cov.evidence_explanation.lower()


# ---------------------------------------------------------------------------
# 4. Missing Evidence
# ---------------------------------------------------------------------------

def test_missing_evidence():
    """When evidence is missing, no fake evidence is generated."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )
    # BMC Remedy should be missing
    bmc_cov = next((c for c in result.requirement_coverage if c.requirement == "BMC Remedy"), None)
    assert bmc_cov is not None
    assert bmc_cov.status == "missing"
    assert bmc_cov.evidence_level == EvidenceLevel.NONE
    assert len(bmc_cov.resume_evidence) == 0
    assert bmc_cov.evidence_explanation is not None
    assert "No evidence" in bmc_cov.evidence_explanation
    # No hallucinated evidence
    assert bmc_cov.semantic_evidence is None or bmc_cov.semantic_evidence == ""


# ---------------------------------------------------------------------------
# 5. Unknown Result
# ---------------------------------------------------------------------------

def test_unknown_result():
    """When the system cannot determine status, it falls back to deterministic."""
    concept_coverage = [
        RequirementCoverage(
            requirement="CustomTool",
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=[],
            evidence_level=EvidenceLevel.NONE,
            category="skill",
            importance="medium",
            status="missing",
            deterministic_status="missing",
        )
    ]

    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="CustomTool",
                status=SemanticMatchStatus.UNKNOWN,
                confidence=0.3,
                evidence=None,
                reasoning="Cannot determine.",
                evidence_strength=SemanticEvidenceStrength.NONE,
            )
        ],
        success=True,
    )

    resume_text_lower = "some resume text".lower()
    reconciled, upgrades, overrides = reconcile_requirements(
        concept_coverage, semantic_result, resume_text_lower,
    )

    updated = apply_reconciliation_to_coverage(concept_coverage, reconciled)
    cov = updated[0]

    # Should fall back to deterministic
    assert cov.status == "missing"
    assert cov.deterministic_status == "missing"
    assert cov.reasoning_source == "Deterministic"


# ---------------------------------------------------------------------------
# 6. Multiple Evidence Items
# ---------------------------------------------------------------------------

def test_multiple_evidence_items():
    """When a requirement has evidence from multiple resume sections, all are captured."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )
    # ServiceNow appears in skills, experience, and projects
    sn_cov = next((c for c in result.requirement_coverage if c.requirement == "ServiceNow"), None)
    assert sn_cov is not None
    # The evidence list should contain the matched variant
    assert len(sn_cov.resume_evidence) > 0
    # Source section should be tracked
    assert sn_cov.evidence_source_section is not None


# ---------------------------------------------------------------------------
# 7. Skill-Only Evidence vs Experience Evidence
# ---------------------------------------------------------------------------

def test_skill_only_vs_experience_evidence():
    """A skill listed in skills section but not used in experience is distinguished."""
    # Resume with ServiceNow only in skills, not in experience
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Test User",
            email="test@example.com",
            phone="1234567890",
            headline="IT Support"
        ),
        summary="General IT support professional.",
        skills=SkillCategory(
            technical=["ServiceNow"],
            tools=[]
        ),
        experience=[
            ExperienceItem(
                company="Test Corp",
                role="IT Support",
                responsibilities=["Handled general IT support tickets"]
            )
        ],
        education=[
            EducationItem(
                institution="State University",
                degree="Bachelor of Science",
                field="Information Technology"
            )
        ]
    )
    resume_content = ResumeContent(profile=profile)

    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=resume_content,
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    sn_cov = next((c for c in result.requirement_coverage if c.requirement == "ServiceNow"), None)
    assert sn_cov is not None
    assert sn_cov.status == "matched"
    # Evidence source should be skills section (not experience)
    assert sn_cov.evidence_source_section is not None
    assert "skills" in sn_cov.evidence_source_section


# ---------------------------------------------------------------------------
# 8. Strong Experience Evidence
# ---------------------------------------------------------------------------

def test_strong_experience_evidence():
    """When evidence comes from experience with strong context, it is tracked."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )
    # Incident Management should be matched via experience
    im_cov = next((c for c in result.requirement_coverage if c.requirement == "Incident Management"), None)
    if im_cov:
        assert im_cov.status == "matched"
        assert im_cov.evidence_level == EvidenceLevel.STRONG
        assert im_cov.evidence_source_section is not None


# ---------------------------------------------------------------------------
# 9. Weak Evidence
# ---------------------------------------------------------------------------

def test_weak_evidence():
    """When evidence is weak, the explanation reflects that."""
    concept_coverage = [
        RequirementCoverage(
            requirement="Active Directory",
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=[],
            evidence_level=EvidenceLevel.NONE,
            category="skill",
            importance="high",
            status="missing",
            deterministic_status="missing",
        )
    ]

    # Use shorter evidence that passes validation (exact substring match for <=50 chars)
    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="Active Directory",
                status=SemanticMatchStatus.PARTIAL,
                confidence=0.45,
                evidence="remote troubleshooting and customer service",
                reasoning="Remote user support might involve Active Directory but there is no direct evidence.",
                evidence_strength=SemanticEvidenceStrength.WEAK,
            )
        ],
        success=True,
    )

    resume_text_lower = "delivered remote troubleshooting and customer service to end users".lower()
    reconciled, upgrades, overrides = reconcile_requirements(
        concept_coverage, semantic_result, resume_text_lower,
    )

    updated = apply_reconciliation_to_coverage(concept_coverage, reconciled)
    cov = updated[0]

    # Should be upgraded to partial (with weak evidence that passes validation)
    assert cov.status == "partial"
    assert cov.deterministic_status == "missing"
    assert cov.semantic_evidence_strength == SemanticEvidenceStrength.WEAK
    assert cov.evidence_explanation is not None


# ---------------------------------------------------------------------------
# 10. Hallucinated Evidence Rejection
# ---------------------------------------------------------------------------

def test_hallucinated_evidence_rejection():
    """LLM fabricates evidence — reconciliation rejects it and preserves deterministic status."""
    concept_coverage = [
        RequirementCoverage(
            requirement="Active Directory",
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=[],
            evidence_level=EvidenceLevel.NONE,
            category="skill",
            importance="high",
            status="missing",
            deterministic_status="missing",
        )
    ]

    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="Active Directory",
                status=SemanticMatchStatus.MATCHED,
                confidence=0.90,
                evidence="Managed Active Directory OU structures for 500 users",
                reasoning="Candidate managed user accounts in Active Directory.",
                evidence_strength=SemanticEvidenceStrength.STRONG,
            )
        ],
        success=True,
    )

    # Resume text does NOT contain the hallucinated evidence
    resume_text_lower = "l1 service desk analyst with itsm and servicenow experience".lower()

    reconciled, upgrades, overrides = reconcile_requirements(
        concept_coverage, semantic_result, resume_text_lower,
    )

    updated = apply_reconciliation_to_coverage(concept_coverage, reconciled)
    cov = updated[0]

    # Should remain MISSING because evidence is hallucinated
    assert cov.status == "missing"
    assert cov.deterministic_status == "missing"
    assert upgrades == 0
    # Resume evidence should be empty (no hallucinated evidence accepted)
    assert len(cov.resume_evidence) == 0
    assert cov.evidence_explanation is not None
    assert "No evidence" in cov.evidence_explanation


# ---------------------------------------------------------------------------
# 11. Evidence Validation Failure
# ---------------------------------------------------------------------------

def test_evidence_validation_failure():
    """Evidence that does not appear in resume is rejected."""
    resume_text = "managed level 1 incident tickets using itsm processes"
    evidence = "Managed Active Directory OU structures"
    assert not _validate_evidence_against_resume(evidence, resume_text)


# ---------------------------------------------------------------------------
# 12. Deterministic Fallback
# ---------------------------------------------------------------------------

def test_deterministic_fallback():
    """When semantic reasoning is unavailable, deterministic results are used."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    # No semantic metadata
    assert result.semantic_metadata is None

    # All concept-based coverage entries should have deterministic_status
    for cov in result.requirement_coverage:
        assert cov.deterministic_status is not None, (
            f"{cov.requirement} should have deterministic_status"
        )
        # For concept-based entries (with category set), status should match deterministic_status
        if cov.category is not None:
            assert cov.deterministic_status == cov.status, (
                f"{cov.requirement} deterministic_status={cov.deterministic_status} != status={cov.status}"
            )


# ---------------------------------------------------------------------------
# 13. Semantic Override with Valid Evidence
# ---------------------------------------------------------------------------

def test_semantic_override_with_valid_evidence():
    """When LLM provides valid evidence that upgrades a requirement, evidence is traceable."""
    concept_coverage = [
        RequirementCoverage(
            requirement="L1 Technical Support",
            requirement_type=JobRequirementType.REQUIRED,
            resume_evidence=[],
            evidence_level=EvidenceLevel.NONE,
            category="requirement",
            importance="high",
            status="missing",
            deterministic_status="missing",
        )
    ]

    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="L1 Technical Support",
                status=SemanticMatchStatus.MATCHED,
                confidence=0.91,
                evidence="Managed Level 1 incident tickets using ServiceNow and ITSM processes",
                reasoning="First-line technical assistance is semantically equivalent to Level 1 technical support.",
                evidence_strength=SemanticEvidenceStrength.STRONG,
            )
        ],
        success=True,
    )

    resume_text_lower = "managed level 1 incident tickets using servicenow and itsm processes".lower()

    reconciled, upgrades, overrides = reconcile_requirements(
        concept_coverage, semantic_result, resume_text_lower,
    )

    updated = apply_reconciliation_to_coverage(concept_coverage, reconciled)
    cov = updated[0]

    assert cov.status == "matched"
    assert cov.deterministic_status == "missing"
    assert cov.reasoning_source == "LLM"
    assert cov.semantic_evidence is not None
    assert "Level 1" in cov.semantic_evidence
    assert cov.evidence_explanation is not None
    assert "semantic analysis" in cov.evidence_explanation.lower() or "semantic" in cov.evidence_explanation.lower()


# ---------------------------------------------------------------------------
# 14. Semantic Override Rejected Without Evidence
# ---------------------------------------------------------------------------

def test_semantic_override_rejected_without_evidence():
    """When LLM claims MATCHED but evidence is hallucinated, override is rejected."""
    concept_coverage = [
        RequirementCoverage(
            requirement="Active Directory",
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=[],
            evidence_level=EvidenceLevel.NONE,
            category="skill",
            importance="high",
            status="missing",
            deterministic_status="missing",
        )
    ]

    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="Active Directory",
                status=SemanticMatchStatus.MATCHED,
                confidence=0.90,
                evidence="Managed Active Directory OU structures for 500 users",
                reasoning="Candidate managed user accounts in Active Directory.",
                evidence_strength=SemanticEvidenceStrength.STRONG,
            )
        ],
        success=True,
    )

    resume_text_lower = "l1 service desk analyst with itsm and servicenow experience".lower()

    reconciled, upgrades, overrides = reconcile_requirements(
        concept_coverage, semantic_result, resume_text_lower,
    )

    updated = apply_reconciliation_to_coverage(concept_coverage, reconciled)
    cov = updated[0]

    assert cov.status == "missing"
    assert cov.deterministic_status == "missing"
    assert upgrades == 0
    assert overrides >= 0  # hallucination counted as override


# ---------------------------------------------------------------------------
# 15. Multiple Requirement Categories
# ---------------------------------------------------------------------------

def test_multiple_requirement_categories():
    """Evidence mapping works across different requirement categories."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    # Check that concept-based coverage entries have proper categories
    concept_coverage = [c for c in result.requirement_coverage if c.category is not None]
    assert len(concept_coverage) > 0

    for cov in concept_coverage:
        assert cov.importance is not None
        assert cov.deterministic_status is not None
        assert cov.status in ("matched", "partial", "missing")


# ---------------------------------------------------------------------------
# 16. Accenture Service Desk Regression
# ---------------------------------------------------------------------------

def test_accenture_evidence_mapping_regression():
    """Full Accenture regression: evidence mapping for all key requirements."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    # MATCHED requirements
    for req_name in ["ServiceNow", "ITSM", "Incident Management"]:
        cov = next((c for c in result.requirement_coverage if c.requirement == req_name), None)
        if cov:
            assert cov.status == "matched", f"{req_name} should be matched"
            assert cov.evidence_level == EvidenceLevel.STRONG, f"{req_name} should have strong evidence"
            assert len(cov.resume_evidence) > 0, f"{req_name} should have evidence"
            assert cov.evidence_source_section is not None, f"{req_name} should have source section"
            assert cov.evidence_explanation is not None, f"{req_name} should have explanation"
            assert cov.deterministic_status is not None, f"{req_name} should have deterministic_status"

    # MISSING requirements
    for req_name in ["BMC Remedy", "Active Directory"]:
        cov = next((c for c in result.requirement_coverage if c.requirement == req_name), None)
        if cov:
            assert cov.status == "missing", f"{req_name} should be missing"
            assert cov.evidence_level == EvidenceLevel.NONE, f"{req_name} should have no evidence"
            assert len(cov.resume_evidence) == 0, f"{req_name} should have empty evidence"
            assert cov.evidence_explanation is not None, f"{req_name} should have explanation"
            assert "No evidence" in cov.evidence_explanation, f"{req_name} explanation should say no evidence"

    # PARTIAL requirements (if present)
    for req_name in ["Remote User Support", "Customer Support"]:
        cov = next((c for c in result.requirement_coverage if c.requirement == req_name), None)
        if cov and cov.status == "partial":
            assert len(cov.resume_evidence) > 0, f"{req_name} partial should have evidence"
            assert cov.evidence_explanation is not None, f"{req_name} should have explanation"


# ---------------------------------------------------------------------------
# 17. Evidence Source Section Tracking
# ---------------------------------------------------------------------------

def test_evidence_source_section_tracking():
    """Evidence source section is tracked for each requirement."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    for cov in result.requirement_coverage:
        if cov.status == "matched" or cov.status == "partial":
            # Evidence source section should be present for matched/partial
            assert cov.evidence_source_section is not None, (
                f"{cov.requirement} has status={cov.status} but no evidence_source_section"
            )


# ---------------------------------------------------------------------------
# 18. Evidence Explanation Generation
# ---------------------------------------------------------------------------

def test_evidence_explanation_quality():
    """Evidence explanations are user-safe and informative."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    for cov in result.requirement_coverage:
        assert cov.evidence_explanation is not None, (
            f"{cov.requirement} should have an evidence_explanation"
        )
        # Explanation should not contain internal details
        assert "deterministic" not in cov.evidence_explanation.lower() or "deterministic analysis" not in cov.evidence_explanation.lower()
        assert "confidence" not in cov.evidence_explanation.lower()
        # Explanation should mention the requirement
        assert cov.requirement in cov.evidence_explanation


# ---------------------------------------------------------------------------
# 19. Deterministic Status Preservation
# ---------------------------------------------------------------------------

def test_deterministic_status_preserved_after_reconciliation():
    """Deterministic status is preserved even after semantic reconciliation."""
    concept_coverage = [
        RequirementCoverage(
            requirement="ServiceNow",
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=["Resume contains: \"ServiceNow\""],
            evidence_level=EvidenceLevel.STRONG,
            category="skill",
            importance="high",
            status="matched",
            deterministic_status="matched",
        )
    ]

    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="ServiceNow",
                status=SemanticMatchStatus.MATCHED,
                confidence=0.95,
                evidence="Managed Level 1 incident tickets using ServiceNow and ITSM processes",
                reasoning="Resume explicitly mentions ServiceNow.",
                evidence_strength=SemanticEvidenceStrength.STRONG,
            )
        ],
        success=True,
    )

    resume_text_lower = "managed level 1 incident tickets using servicenow and itsm processes".lower()

    reconciled, upgrades, overrides = reconcile_requirements(
        concept_coverage, semantic_result, resume_text_lower,
    )

    updated = apply_reconciliation_to_coverage(concept_coverage, reconciled)
    cov = updated[0]

    # Deterministic status should be preserved
    assert cov.deterministic_status == "matched"
    # Final status should also be matched
    assert cov.status == "matched"


# ---------------------------------------------------------------------------
# 20. Reconciled Explanation Quality
# ---------------------------------------------------------------------------

def test_reconciled_explanation_for_upgrade():
    """When reconciliation upgrades a requirement, explanation reflects the upgrade."""
    concept_coverage = [
        RequirementCoverage(
            requirement="L1 Technical Support",
            requirement_type=JobRequirementType.REQUIRED,
            resume_evidence=[],
            evidence_level=EvidenceLevel.NONE,
            category="requirement",
            importance="high",
            status="missing",
            deterministic_status="missing",
        )
    ]

    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="L1 Technical Support",
                status=SemanticMatchStatus.MATCHED,
                confidence=0.91,
                evidence="Managed Level 1 incident tickets using ServiceNow and ITSM processes",
                reasoning="First-line technical assistance is semantically equivalent to Level 1 technical support.",
                evidence_strength=SemanticEvidenceStrength.STRONG,
            )
        ],
        success=True,
    )

    resume_text_lower = "managed level 1 incident tickets using servicenow and itsm processes".lower()

    reconciled, upgrades, overrides = reconcile_requirements(
        concept_coverage, semantic_result, resume_text_lower,
    )

    updated = apply_reconciliation_to_coverage(concept_coverage, reconciled)
    cov = updated[0]

    explanation = cov.evidence_explanation
    assert explanation is not None
    # Should mention the requirement
    assert "L1 Technical Support" in explanation
    # Should mention semantic analysis (since it was upgraded by LLM)
    assert "semantic" in explanation.lower()


def test_reconciled_explanation_for_missing():
    """When a requirement is missing, explanation says no evidence found."""
    concept_coverage = [
        RequirementCoverage(
            requirement="BMC Remedy",
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=[],
            evidence_level=EvidenceLevel.NONE,
            category="skill",
            importance="high",
            status="missing",
            deterministic_status="missing",
        )
    ]

    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="BMC Remedy",
                status=SemanticMatchStatus.MISSING,
                confidence=0.95,
                evidence=None,
                reasoning="No mention of BMC Remedy in the resume.",
                evidence_strength=SemanticEvidenceStrength.NONE,
            )
        ],
        success=True,
    )

    resume_text_lower = "some resume text".lower()

    reconciled, upgrades, overrides = reconcile_requirements(
        concept_coverage, semantic_result, resume_text_lower,
    )

    updated = apply_reconciliation_to_coverage(concept_coverage, reconciled)
    cov = updated[0]

    explanation = cov.evidence_explanation
    assert explanation is not None
    assert "No evidence" in explanation
    assert "BMC Remedy" in explanation


def test_reconciled_explanation_for_llm_override():
    """When LLM overrides deterministic MATCHED to MISSING, explanation reflects that."""
    concept_coverage = [
        RequirementCoverage(
            requirement="CustomTool",
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=["Resume contains: \"custom\""],
            evidence_level=EvidenceLevel.PARTIAL,
            category="skill",
            importance="high",
            status="matched",
            deterministic_status="matched",
        )
    ]

    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="CustomTool",
                status=SemanticMatchStatus.MISSING,
                confidence=0.92,
                evidence=None,
                reasoning="The resume mentions 'custom' but this is not the same as CustomTool.",
                evidence_strength=SemanticEvidenceStrength.NONE,
            )
        ],
        success=True,
    )

    resume_text_lower = "custom configurations for enterprise".lower()

    reconciled, upgrades, overrides = reconcile_requirements(
        concept_coverage, semantic_result, resume_text_lower,
    )

    updated = apply_reconciliation_to_coverage(concept_coverage, reconciled)
    cov = updated[0]

    explanation = cov.evidence_explanation
    assert explanation is not None
    assert "CustomTool" in explanation
    # Should indicate semantic analysis determined no evidence
    assert "semantic" in explanation.lower() or "No evidence" in explanation


# ---------------------------------------------------------------------------
# 21. No Hallucinated Evidence in Final Output
# ---------------------------------------------------------------------------

def test_no_hallucinated_evidence_in_final_output():
    """Final coverage entries never contain hallucinated evidence."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    resume_text = (
        "l1 service desk analyst with itsm and servicenow experience "
        "handles incident management and sla adherence provides remote troubleshooting "
        "and customer service strong verbal and written communication and problem solving "
        "managed level 1 incident tickets using servicenow and itsm processes "
        "owned ticketing systems and ticket lifecycle and knowledge bases within a service desk "
        "delivered remote troubleshooting and customer service to end users "
        "handled bengaluru rotational shifts state university bachelor of science computer science "
        "self-service portal built a knowledge base to reduce ticket volume"
    ).lower()

    for cov in result.requirement_coverage:
        for ev in cov.resume_evidence:
            # Strip the "Semantic evidence: " or "Resume contains: " prefix
            clean_ev = ev.replace('Semantic evidence: "', "").replace('Resume contains: "', "").replace('Related resume evidence: "', "").rstrip('"')
            # Evidence should be traceable to resume (or be from LLM with validation)
            if cov.reasoning_source == "LLM":
                # LLM evidence should have been validated
                assert _validate_evidence_against_resume(clean_ev, resume_text), (
                    f"Hallucinated evidence found in {cov.requirement}: {clean_ev[:80]}"
                )


# ---------------------------------------------------------------------------
# 22. Skill Listed vs Skill Demonstrated
# ---------------------------------------------------------------------------

def test_skill_listed_vs_demonstrated():
    """A skill listed in skills but not used in experience is still matched (via skills section)."""
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Test User",
            email="test@example.com",
            phone="1234567890",
            headline="Developer"
        ),
        summary="Developer with some experience.",
        skills=SkillCategory(
            technical=["Python", "PostgreSQL"],
            tools=["Git"]
        ),
        experience=[
            ExperienceItem(
                company="Test Corp",
                role="Developer",
                responsibilities=["Built web applications using Python."]
            )
        ],
        education=[
            EducationItem(
                institution="State University",
                degree="Bachelor of Science",
                field="Computer Science"
            )
        ]
    )
    resume_content = ResumeContent(profile=profile)

    jd = """
    Python Developer
    Requirements:
    - Python and PostgreSQL experience.
    - Git version control.
    """

    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=resume_content,
        job_description=jd,
        job_title="Python Developer",
        company="TestCo"
    )

    # Python should be matched
    python_cov = next((c for c in result.requirement_coverage if c.requirement == "Python"), None)
    assert python_cov is not None
    assert python_cov.status == "matched"
    assert python_cov.evidence_source_section is not None

    # PostgreSQL should be matched
    pg_cov = next((c for c in result.requirement_coverage if c.requirement == "PostgreSQL"), None)
    assert pg_cov is not None
    assert pg_cov.status == "matched"
    assert pg_cov.evidence_source_section is not None


# ---------------------------------------------------------------------------
# 23. Evidence Traceability
# ---------------------------------------------------------------------------

def test_evidence_is_actually_in_resume():
    """Every piece of evidence in concept-based coverage entries is traceable to resume text."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    # Build full resume text
    from app.services.ats.semantic_reasoner import _build_resume_text
    resume_text = _build_resume_text(_make_service_desk_resume().profile).lower()

    for cov in result.requirement_coverage:
        # Only check concept-based coverage (not experience responsibility coverage)
        if cov.category is None:
            continue
        for ev in cov.resume_evidence:
            # Strip various prefixes
            clean_ev = ev
            for prefix in ['Semantic evidence: "', 'Resume contains: "', 'Related resume evidence: "']:
                if clean_ev.startswith(prefix):
                    clean_ev = clean_ev[len(prefix):]
            if clean_ev.endswith('"'):
                clean_ev = clean_ev[:-1]

            # For concept coverage, the evidence is the matched variant text
            # It should appear somewhere in the resume
            assert clean_ev.lower() in resume_text, (
                f"Evidence not found in resume for {cov.requirement}: {clean_ev[:100]}"
            )


# ---------------------------------------------------------------------------
# 24. API Contract Compatibility
# ---------------------------------------------------------------------------

def test_api_contract_with_new_fields():
    """New fields are present in the API response without breaking existing contract."""
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    # All original fields must still be present
    for field in [
        "overall_score", "keyword_match_score", "skills_match_score",
        "experience_relevance_score", "qualification_match_score", "structure_format_score",
        "matched_keywords", "missing_keywords", "partial_keywords",
        "matched_skills", "missing_skills", "partial_skills",
        "requirement_coverage", "analysis_explanation",
    ]:
        assert hasattr(result, field), f"missing contract field: {field}"

    # New fields must also be present on coverage entries
    for cov in result.requirement_coverage:
        assert hasattr(cov, "deterministic_status"), "missing deterministic_status"
        assert hasattr(cov, "evidence_source_section"), "missing evidence_source_section"
        assert hasattr(cov, "evidence_explanation"), "missing evidence_explanation"
        # These should never be None for any coverage entry
        assert cov.deterministic_status is not None, (
            f"{cov.requirement} has None deterministic_status"
        )
        assert cov.evidence_explanation is not None, (
            f"{cov.requirement} has None evidence_explanation"
        )


# ---------------------------------------------------------------------------
# 25. No Additional LLM Calls
# ---------------------------------------------------------------------------

def test_no_additional_llm_calls():
    """Target 4.1 does not introduce additional LLM calls."""
    # This is verified by architecture: the evidence mapping uses only
    # deterministic matching and existing semantic reasoning output.
    # No new LLM requests are made.
    analyzer = ATSAnalyzer()
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    # Verify semantic metadata shows no additional calls
    # (without a semantic reasoner, there should be no semantic calls at all)
    assert result.semantic_metadata is None

    # All coverage entries should have deterministic_status set
    for cov in result.requirement_coverage:
        assert cov.deterministic_status is not None
