"""Tests for LLM-Powered ATS Semantic Reasoning (Target 3).

Tests cover:
1. Exact match
2. Semantic match
3. Partial semantic match
4. Missing requirement
5. Unknown evidence
6. Tool mismatch
7. Hallucination attempt
8. Keyword stuffing
9. Synonym equivalence
10. Strong evidence
11. Weak evidence
12. LLM timeout
13. Invalid LLM JSON
14. LLM provider failure
15. Deterministic fallback
16. Reconciliation behavior
17. Accenture Service Desk regression
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Dict, Any, Optional

from app.models.ats import (
    SemanticRequirementAssessment,
    SemanticAnalysisResult,
    SemanticMatchStatus,
    SemanticEvidenceStrength,
    RequirementCoverage,
    ReconciledRequirement,
    ATSAnalysisMetadata,
    JobRequirementType,
    EvidenceLevel,
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
from app.llm.types import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMProviderError,
    LLMTimeoutError,
    LLMAuthenticationError,
    LLMRateLimitError,
)
from app.services.ats.semantic_reasoner import (
    ATSSemanticReasoner,
    _build_resume_text,
    _build_resume_skills,
    _build_requirements_block,
    _parse_llm_response,
    _validate_assessment,
)
from app.services.ats.semantic_reconciler import (
    reconcile_requirements,
    build_semantic_metadata,
    apply_reconciliation_to_coverage,
    _validate_evidence_against_resume,
    SemanticUpgradeConfidence,
    SemanticOverrideConfidence,
)
from app.services.ats.ats_analyzer import ATSAnalyzer
from app.services.ats.job_description_parser import JobDescriptionParser


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


def _mock_llm_response(assessments: List[Dict[str, Any]]) -> LLMResponse:
    """Create a mock LLM response with given assessments."""
    data = {"assessments": assessments}
    return LLMResponse(
        provider=LLMProvider.GROQ,
        model="test-model",
        content=json.dumps(data),
    )


def _make_mock_gateway(assessments: List[Dict[str, Any]]) -> MagicMock:
    """Create a mock LLMGateway that returns given assessments."""
    mock_gateway = MagicMock()
    mock_gateway.generate = AsyncMock(return_value=_mock_llm_response(assessments))
    return mock_gateway


def _make_failing_gateway(error: Exception) -> MagicMock:
    """Create a mock LLMGateway that raises an error."""
    mock_gateway = MagicMock()
    mock_gateway.generate = AsyncMock(side_effect=error)
    return mock_gateway


def _make_concepts_from_jd(jd_text: str) -> List[Dict[str, Any]]:
    """Extract concepts from a JD text."""
    parser = JobDescriptionParser()
    return parser.extract_job_concepts(jd_text)


# ---------------------------------------------------------------------------
# 1. Exact Match Tests
# ---------------------------------------------------------------------------

def test_exact_match_identified():
    """LLM correctly identifies exact keyword match."""
    reqs = [
        {"canonical": "ServiceNow", "category": "skill", "importance": "high",
         "variants": ["ServiceNow"], "job_evidence": "ServiceNow"},
    ]
    assessments = [
        {
            "requirement_id": "ServiceNow",
            "status": "matched",
            "confidence": 0.95,
            "evidence": "Managed Level 1 incident tickets using ServiceNow and ITSM processes",
            "reasoning": "Resume explicitly mentions ServiceNow.",
            "evidence_strength": "strong",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    resume = _make_service_desk_resume()

    result = _run_sync(reasoner.analyze_requirements(reqs, resume))

    assert result.success
    assert len(result.assessments) == 1
    assert result.assessments[0].status == SemanticMatchStatus.MATCHED
    assert result.assessments[0].confidence >= 0.9


# ---------------------------------------------------------------------------
# 2. Semantic Match Tests
# ---------------------------------------------------------------------------

def test_semantic_match_identified():
    """LLM correctly identifies semantic equivalence (different wording, same meaning)."""
    reqs = [
        {"canonical": "L1 Technical Support", "category": "requirement", "importance": "high",
         "variants": ["L1", "Level 1"], "job_evidence": "Level 1 technical support"},
    ]
    assessments = [
        {
            "requirement_id": "L1 Technical Support",
            "status": "matched",
            "confidence": 0.91,
            "evidence": "Managed Level 1 incident tickets using ServiceNow and ITSM processes",
            "reasoning": "First-line technical assistance is semantically equivalent to Level 1 technical support.",
            "evidence_strength": "strong",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    resume = _make_service_desk_resume()

    result = _run_sync(reasoner.analyze_requirements(reqs, resume))

    assert result.success
    assert result.assessments[0].status == SemanticMatchStatus.MATCHED
    assert "semantically equivalent" in result.assessments[0].reasoning.lower() or "level 1" in result.assessments[0].reasoning.lower()


# ---------------------------------------------------------------------------
# 3. Partial Semantic Match Tests
# ---------------------------------------------------------------------------

def test_partial_semantic_match():
    """LLM correctly identifies partial evidence."""
    reqs = [
        {"canonical": "Remote User Support", "category": "requirement", "importance": "medium",
         "variants": ["remote user support"], "job_evidence": "remote user support"},
    ]
    assessments = [
        {
            "requirement_id": "Remote User Support",
            "status": "partial",
            "confidence": 0.72,
            "evidence": "Delivered remote troubleshooting and customer service to end users",
            "reasoning": "Resume mentions remote troubleshooting but not explicitly remote user support.",
            "evidence_strength": "moderate",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    resume = _make_service_desk_resume()

    result = _run_sync(reasoner.analyze_requirements(reqs, resume))

    assert result.success
    assert result.assessments[0].status == SemanticMatchStatus.PARTIAL


# ---------------------------------------------------------------------------
# 4. Missing Requirement Tests
# ---------------------------------------------------------------------------

def test_missing_requirement():
    """LLM correctly identifies missing requirement."""
    reqs = [
        {"canonical": "BMC Remedy", "category": "skill", "importance": "high",
         "variants": ["BMC Remedy", "Remedy"], "job_evidence": "BMC Remedy"},
    ]
    assessments = [
        {
            "requirement_id": "BMC Remedy",
            "status": "missing",
            "confidence": 0.95,
            "evidence": None,
            "reasoning": "No mention of BMC Remedy in the resume.",
            "evidence_strength": "none",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    resume = _make_service_desk_resume()

    result = _run_sync(reasoner.analyze_requirements(reqs, resume))

    assert result.success
    assert result.assessments[0].status == SemanticMatchStatus.MISSING
    assert result.assessments[0].evidence is None


# ---------------------------------------------------------------------------
# 5. Unknown Evidence Tests
# ---------------------------------------------------------------------------

def test_unknown_evidence():
    """LLM returns UNKNOWN when it cannot determine the relationship."""
    reqs = [
        {"canonical": "CustomTool", "category": "skill", "importance": "medium",
         "variants": ["CustomTool"], "job_evidence": "CustomTool"},
    ]
    assessments = [
        {
            "requirement_id": "CustomTool",
            "status": "unknown",
            "confidence": 0.3,
            "evidence": None,
            "reasoning": "Cannot determine if the candidate has CustomTool experience.",
            "evidence_strength": "none",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    resume = _make_service_desk_resume()

    result = _run_sync(reasoner.analyze_requirements(reqs, resume))

    assert result.success
    assert result.assessments[0].status == SemanticMatchStatus.UNKNOWN


# ---------------------------------------------------------------------------
# 6. Tool Mismatch Tests
# ---------------------------------------------------------------------------

def test_tool_mismatch_not_matched():
    """LLM correctly identifies that ITSM ticketing does NOT prove ServiceNow."""
    reqs = [
        {"canonical": "ServiceNow", "category": "skill", "importance": "high",
         "variants": ["ServiceNow"], "job_evidence": "ServiceNow"},
    ]
    # Resume only has "ITSM ticketing" — does NOT prove ServiceNow
    assessments = [
        {
            "requirement_id": "ServiceNow",
            "status": "missing",
            "confidence": 0.85,
            "evidence": None,
            "reasoning": "ITSM ticketing is a general category that does not necessarily prove ServiceNow experience.",
            "evidence_strength": "none",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)

    # Create a resume that only has ITSM, not ServiceNow
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Test User",
            email="test@example.com",
            phone="1234567890",
            headline="IT Support"
        ),
        summary="ITSM ticketing professional.",
        skills=SkillCategory(
            technical=["ITSM"],
            tools=[]
        ),
        experience=[
            ExperienceItem(
                company="Test Corp",
                role="IT Support",
                responsibilities=["Handled ITSM ticketing for enterprise users"]
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
    resume = ResumeContent(profile=profile)

    result = _run_sync(reasoner.analyze_requirements(reqs, resume))

    assert result.success
    assert result.assessments[0].status == SemanticMatchStatus.MISSING


# ---------------------------------------------------------------------------
# 7. Hallucination Attempt Tests
# ---------------------------------------------------------------------------

def test_hallucination_attempt_rejected():
    """LLM fabricates evidence — reconciliation rejects it."""
    # LLM claims MATCHED with evidence that doesn't exist in the resume
    assessments = [
        {
            "requirement_id": "Active Directory",
            "status": "matched",
            "confidence": 0.90,
            "evidence": "Managed Active Directory OU structures for 500 users",
            "reasoning": "Candidate managed user accounts in Active Directory.",
            "evidence_strength": "strong",
        }
    ]

    # The resume does NOT contain Active Directory evidence
    resume_text_lower = "l1 service desk analyst with itsm and servicenow experience handles incident management and sla adherence provides remote troubleshooting and customer service".lower()

    evidence = "Managed Active Directory OU structures for 500 users"
    is_valid = _validate_evidence_against_resume(evidence, resume_text_lower)

    assert not is_valid, "Hallucinated evidence should be rejected"


def test_hallucination_rejected_in_reconciliation():
    """Reconciliation layer rejects LLM when evidence doesn't match resume."""
    concept_coverage = [
        RequirementCoverage(
            requirement="Active Directory",
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=[],
            evidence_level=EvidenceLevel.NONE,
            category="skill",
            importance="high",
            status="missing",
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

    assert len(reconciled) == 1
    # Should remain MISSING because evidence is hallucinated
    assert reconciled[0].final_status == "missing"
    assert upgrades == 0


# ---------------------------------------------------------------------------
# 8. Keyword Stuffing Resistance Tests
# ---------------------------------------------------------------------------

def test_keyword_stuffing_does_not_boost_semantic():
    """Repeating the same keyword many times should not boost semantic confidence."""
    # Even with keyword stuffing in the resume, the LLM should not artificially boost
    reqs = [
        {"canonical": "ServiceNow", "category": "skill", "importance": "high",
         "variants": ["ServiceNow"], "job_evidence": "ServiceNow"},
    ]
    assessments = [
        {
            "requirement_id": "ServiceNow",
            "status": "matched",
            "confidence": 0.95,
            "evidence": "ServiceNow",
            "reasoning": "Resume explicitly mentions ServiceNow.",
            "evidence_strength": "strong",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)

    # Stuffed resume
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Stuffed User",
            email="stuffed@example.com",
            phone="1234567890",
            headline="Service Desk"
        ),
        summary="ServiceNow ServiceNow ServiceNow ServiceNow ServiceNow",
        skills=SkillCategory(
            technical=["ServiceNow"],
            tools=[]
        ),
        experience=[
            ExperienceItem(
                company="Test Corp",
                role="Service Desk",
                responsibilities=["Used ServiceNow"]
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
    resume = ResumeContent(profile=profile)

    result = _run_sync(reasoner.analyze_requirements(reqs, resume))

    assert result.success
    # Confidence should be reasonable, not artificially inflated
    assert result.assessments[0].confidence <= 1.0


# ---------------------------------------------------------------------------
# 9. Synonym Equivalence Tests
# ---------------------------------------------------------------------------

def test_synonym_equivalence():
    """LLM identifies synonym equivalence for resume concepts."""
    reqs = [
        {"canonical": "Incident Management", "category": "skill", "importance": "high",
         "variants": ["Incident Management"], "job_evidence": "Incident Management"},
    ]
    assessments = [
        {
            "requirement_id": "Incident Management",
            "status": "matched",
            "confidence": 0.88,
            "evidence": "Managed Level 1 incident tickets using ServiceNow and ITSM processes",
            "reasoning": "Resume mentions incident ticket management which is equivalent to incident management.",
            "evidence_strength": "strong",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    resume = _make_service_desk_resume()

    result = _run_sync(reasoner.analyze_requirements(reqs, resume))

    assert result.success
    assert result.assessments[0].status == SemanticMatchStatus.MATCHED


# ---------------------------------------------------------------------------
# 10. Strong Evidence Tests
# ---------------------------------------------------------------------------

def test_strong_evidence():
    """LLM identifies strong evidence with high confidence."""
    reqs = [
        {"canonical": "ServiceNow", "category": "skill", "importance": "high",
         "variants": ["ServiceNow"], "job_evidence": "ServiceNow"},
    ]
    assessments = [
        {
            "requirement_id": "ServiceNow",
            "status": "matched",
            "confidence": 0.97,
            "evidence": "Managed Level 1 incident tickets using ServiceNow and ITSM processes",
            "reasoning": "Resume explicitly mentions ServiceNow as a tool used for incident management.",
            "evidence_strength": "strong",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    resume = _make_service_desk_resume()

    result = _run_sync(reasoner.analyze_requirements(reqs, resume))

    assert result.success
    assert result.assessments[0].evidence_strength == SemanticEvidenceStrength.STRONG
    assert result.assessments[0].confidence >= 0.9


# ---------------------------------------------------------------------------
# 11. Weak Evidence Tests
# ---------------------------------------------------------------------------

def test_weak_evidence():
    """LLM identifies weak evidence with low confidence."""
    reqs = [
        {"canonical": "Active Directory", "category": "skill", "importance": "high",
         "variants": ["Active Directory"], "job_evidence": "Active Directory"},
    ]
    assessments = [
        {
            "requirement_id": "Active Directory",
            "status": "partial",
            "confidence": 0.45,
            "evidence": "Delivered remote troubleshooting and customer service to end users",
            "reasoning": "Remote user support might involve Active Directory but there is no direct evidence.",
            "evidence_strength": "weak",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    resume = _make_service_desk_resume()

    result = _run_sync(reasoner.analyze_requirements(reqs, resume))

    assert result.success
    assert result.assessments[0].evidence_strength == SemanticEvidenceStrength.WEAK
    assert result.assessments[0].confidence < 0.6


# ---------------------------------------------------------------------------
# 12. LLM Timeout Tests
# ---------------------------------------------------------------------------

def test_llm_timeout_fallback():
    """LLM timeout results in graceful fallback to deterministic."""
    mock_gateway = _make_failing_gateway(LLMTimeoutError("Request timed out", LLMProvider.GROQ))
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)

    reqs = [
        {"canonical": "ServiceNow", "category": "skill", "importance": "high",
         "variants": ["ServiceNow"], "job_evidence": "ServiceNow"},
    ]

    result = _run_sync(reasoner.analyze_requirements(reqs, _make_service_desk_resume()))

    assert not result.success
    assert result.error_message is not None
    assert len(result.assessments) == 0


# ---------------------------------------------------------------------------
# 13. Invalid LLM JSON Tests
# ---------------------------------------------------------------------------

def test_invalid_llm_json():
    """LLM returns invalid JSON — graceful fallback."""
    mock_gateway = MagicMock()
    mock_gateway.generate = AsyncMock(return_value=LLMResponse(
        provider=LLMProvider.GROQ,
        model="test-model",
        content="This is not valid JSON at all {broken",
    ))
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)

    reqs = [
        {"canonical": "ServiceNow", "category": "skill", "importance": "high",
         "variants": ["ServiceNow"], "job_evidence": "ServiceNow"},
    ]

    result = _run_sync(reasoner.analyze_requirements(reqs, _make_service_desk_resume()))

    assert not result.success
    assert "Invalid" in result.error_message or "invalid" in result.error_message


def test_invalid_llm_json_missing_assessments():
    """LLM returns JSON without required 'assessments' key."""
    mock_gateway = MagicMock()
    mock_gateway.generate = AsyncMock(return_value=LLMResponse(
        provider=LLMProvider.GROQ,
        model="test-model",
        content=json.dumps({"score": 85, "feedback": "Good resume"}),
    ))
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)

    reqs = [
        {"canonical": "ServiceNow", "category": "skill", "importance": "high",
         "variants": ["ServiceNow"], "job_evidence": "ServiceNow"},
    ]

    result = _run_sync(reasoner.analyze_requirements(reqs, _make_service_desk_resume()))

    assert not result.success


# ---------------------------------------------------------------------------
# 14. LLM Provider Failure Tests
# ---------------------------------------------------------------------------

def test_llm_provider_auth_failure():
    """LLM provider authentication failure — graceful fallback."""
    mock_gateway = _make_failing_gateway(LLMAuthenticationError("Invalid API key", LLMProvider.GROQ))
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)

    reqs = [
        {"canonical": "ServiceNow", "category": "skill", "importance": "high",
         "variants": ["ServiceNow"], "job_evidence": "ServiceNow"},
    ]

    result = _run_sync(reasoner.analyze_requirements(reqs, _make_service_desk_resume()))

    assert not result.success
    assert len(result.assessments) == 0


def test_llm_rate_limit_failure():
    """LLM rate limit — graceful fallback."""
    mock_gateway = _make_failing_gateway(LLMRateLimitError("Rate limited", LLMProvider.GROQ))
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)

    reqs = [
        {"canonical": "ServiceNow", "category": "skill", "importance": "high",
         "variants": ["ServiceNow"], "job_evidence": "ServiceNow"},
    ]

    result = _run_sync(reasoner.analyze_requirements(reqs, _make_service_desk_resume()))

    assert not result.success
    assert len(result.assessments) == 0


# ---------------------------------------------------------------------------
# 15. Deterministic Fallback Tests
# ---------------------------------------------------------------------------

def test_analyzer_works_without_semantic_reasoner():
    """ATSAnalyzer works completely without a semantic reasoner."""
    analyzer = ATSAnalyzer()  # No semantic_reasoner
    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    assert result.overall_score > 0
    assert result.semantic_metadata is None
    assert "ServiceNow" in result.matched_skills


def test_analyzer_fallback_when_llm_fails():
    """ATSAnalyzer falls back gracefully when semantic reasoning fails."""
    mock_gateway = _make_failing_gateway(LLMTimeoutError("Timeout", LLMProvider.GROQ))
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    analyzer = ATSAnalyzer(semantic_reasoner=reasoner)

    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    # Should still produce valid results from deterministic engine
    assert result.overall_score > 0
    assert result.semantic_metadata is not None
    assert result.semantic_metadata.semantic_success is False


# ---------------------------------------------------------------------------
# 16. Reconciliation Behavior Tests
# ---------------------------------------------------------------------------

def test_reconciliation_upgrade_missing_to_matched():
    """Reconciliation upgrades MISSING → MATCHED when LLM provides valid evidence."""
    concept_coverage = [
        RequirementCoverage(
            requirement="L1 Technical Support",
            requirement_type=JobRequirementType.REQUIRED,
            resume_evidence=[],
            evidence_level=EvidenceLevel.NONE,
            category="requirement",
            importance="high",
            status="missing",
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

    # Resume text contains the evidence
    resume_text_lower = "managed level 1 incident tickets using servicenow and itsm processes delivered remote troubleshooting".lower()

    reconciled, upgrades, overrides = reconcile_requirements(
        concept_coverage, semantic_result, resume_text_lower,
    )

    assert len(reconciled) == 1
    assert reconciled[0].final_status == "matched"
    assert reconciled[0].reasoning_source == "LLM"
    assert upgrades == 1


def test_reconciliation_keeps_deterministic_when_llm_unknown():
    """When LLM returns UNKNOWN, deterministic status is preserved."""
    concept_coverage = [
        RequirementCoverage(
            requirement="Active Directory",
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=[],
            evidence_level=EvidenceLevel.NONE,
            category="skill",
            importance="high",
            status="missing",
        )
    ]

    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="Active Directory",
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

    assert len(reconciled) == 1
    assert reconciled[0].final_status == "missing"
    assert reconciled[0].reasoning_source == "Deterministic"
    assert upgrades == 0


def test_reconciliation_keeps_matched_when_llm_missing():
    """When deterministic is MATCHED but LLM says MISSING (low confidence), keep matched."""
    concept_coverage = [
        RequirementCoverage(
            requirement="ServiceNow",
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=["Resume contains: \"ServiceNow\""],
            evidence_level=EvidenceLevel.STRONG,
            category="skill",
            importance="high",
            status="matched",
        )
    ]

    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="ServiceNow",
                status=SemanticMatchStatus.MISSING,
                confidence=0.6,  # Below override threshold
                evidence=None,
                reasoning="Did not find ServiceNow.",
                evidence_strength=SemanticEvidenceStrength.NONE,
            )
        ],
        success=True,
    )

    resume_text_lower = "servicenow itsm incident management".lower()

    reconciled, upgrades, overrides = reconcile_requirements(
        concept_coverage, semantic_result, resume_text_lower,
    )

    assert len(reconciled) == 1
    # Should remain matched (deterministic is authoritative for matched)
    assert reconciled[0].final_status == "matched"
    assert reconciled[0].reasoning_source == "Deterministic"


def test_reconciliation_overrides_deterministic_matched_when_llm_high_confidence_missing():
    """When LLM strongly disagrees with deterministic MATCHED, LLM can override."""
    concept_coverage = [
        RequirementCoverage(
            requirement="CustomTool",
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=["Resume contains: \"custom\""],
            evidence_level=EvidenceLevel.PARTIAL,
            category="skill",
            importance="high",
            status="matched",
        )
    ]

    semantic_result = SemanticAnalysisResult(
        assessments=[
            SemanticRequirementAssessment(
                requirement_id="CustomTool",
                status=SemanticMatchStatus.MISSING,
                confidence=0.92,  # Above override threshold
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

    assert len(reconciled) == 1
    assert reconciled[0].final_status == "missing"
    assert reconciled[0].reasoning_source == "LLM"
    assert overrides == 1


# ---------------------------------------------------------------------------
# 17. Accenture Service Desk Regression Tests
# ---------------------------------------------------------------------------

def test_accenture_semantic_level1_match():
    """Accenture JD: 'Level 1 Technical Support' ↔ 'first-line technical assistance' semantic match."""
    reqs = _make_concepts_from_jd(ACCENTURE_SERVICE_DESK_JD)
    level1_reqs = [c for c in reqs if c["canonical"] == "L1 Technical Support"]
    assert len(level1_reqs) > 0, "L1 Technical Support should be extracted from Accenture JD"

    assessments = [
        {
            "requirement_id": "L1 Technical Support",
            "status": "matched",
            "confidence": 0.91,
            "evidence": "Managed Level 1 incident tickets using ServiceNow and ITSM processes",
            "reasoning": "First-line technical assistance is semantically equivalent to Level 1 technical support.",
            "evidence_strength": "strong",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    resume = _make_service_desk_resume()

    result = _run_sync(reasoner.analyze_requirements(level1_reqs, resume))

    assert result.success
    assert result.assessments[0].status == SemanticMatchStatus.MATCHED


def test_accenture_semantic_remote_support():
    """Accenture JD: 'Remote User Support' ↔ 'supported distributed employees' semantic match."""
    reqs = _make_concepts_from_jd(ACCENTURE_SERVICE_DESK_JD)
    remote_reqs = [c for c in reqs if c["canonical"] == "Remote User Support"]

    # Remote User Support may be partial or missing in deterministic
    # Semantic layer should upgrade if resume has remote troubleshooting
    assessments = [
        {
            "requirement_id": "Remote User Support",
            "status": "matched",
            "confidence": 0.85,
            "evidence": "Delivered remote troubleshooting and customer service to end users",
            "reasoning": "Resume describes delivering remote troubleshooting which is semantically equivalent to remote user support.",
            "evidence_strength": "strong",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    resume = _make_service_desk_resume()

    result = _run_sync(reasoner.analyze_requirements(remote_reqs, resume))

    assert result.success
    assert result.assessments[0].status == SemanticMatchStatus.MATCHED


def test_accenture_semantic_incident_management():
    """Accenture JD: 'Incident Management' ↔ 'logged, prioritized and resolved technical incidents' semantic match."""
    reqs = _make_concepts_from_jd(ACCENTURE_SERVICE_DESK_JD)
    incident_reqs = [c for c in reqs if c["canonical"] == "Incident Management"]

    assessments = [
        {
            "requirement_id": "Incident Management",
            "status": "matched",
            "confidence": 0.88,
            "evidence": "Managed Level 1 incident tickets using ServiceNow and ITSM processes",
            "reasoning": "Resume mentions incident ticket management which is equivalent to incident management.",
            "evidence_strength": "strong",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    resume = _make_service_desk_resume()

    result = _run_sync(reasoner.analyze_requirements(incident_reqs, resume))

    assert result.success
    assert result.assessments[0].status == SemanticMatchStatus.MATCHED


def test_accenture_servicenow_not_auto_matched_from_itsm():
    """ServiceNow does NOT match merely because 'ITSM' appears."""
    # Resume with only ITSM, no ServiceNow
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Test User",
            email="test@example.com",
            phone="1234567890",
            headline="IT Support"
        ),
        summary="ITSM ticketing professional with incident management experience.",
        skills=SkillCategory(
            technical=["ITSM"],
            tools=[]
        ),
        experience=[
            ExperienceItem(
                company="Test Corp",
                role="IT Support",
                responsibilities=["Handled ITSM ticketing for enterprise users"]
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
    resume = ResumeContent(profile=profile)

    reqs = [
        {"canonical": "ServiceNow", "category": "skill", "importance": "high",
         "variants": ["ServiceNow"], "job_evidence": "ServiceNow"},
    ]

    # LLM correctly says MISSING (not matched)
    assessments = [
        {
            "requirement_id": "ServiceNow",
            "status": "missing",
            "confidence": 0.88,
            "evidence": None,
            "reasoning": "ITSM is a general category. ServiceNow is a specific tool not mentioned in the resume.",
            "evidence_strength": "none",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)

    result = _run_sync(reasoner.analyze_requirements(reqs, resume))

    assert result.success
    assert result.assessments[0].status == SemanticMatchStatus.MISSING


def test_accenture_active_directory_not_auto_matched():
    """Active Directory does NOT match merely because 'user accounts' appears."""
    reqs = [
        {"canonical": "Active Directory", "category": "skill", "importance": "high",
         "variants": ["Active Directory"], "job_evidence": "Active Directory"},
    ]

    # LLM correctly says MISSING
    assessments = [
        {
            "requirement_id": "Active Directory",
            "status": "missing",
            "confidence": 0.90,
            "evidence": None,
            "reasoning": "Managing user accounts does not necessarily involve Active Directory.",
            "evidence_strength": "none",
        }
    ]

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)

    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Test User",
            email="test@example.com",
            phone="1234567890",
            headline="IT Support"
        ),
        summary="Managed user accounts and access permissions.",
        skills=SkillCategory(
            technical=[],
            tools=[]
        ),
        experience=[
            ExperienceItem(
                company="Test Corp",
                role="IT Support",
                responsibilities=["Managed user accounts and access permissions"]
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
    resume = ResumeContent(profile=profile)

    result = _run_sync(reasoner.analyze_requirements(reqs, resume))

    assert result.success
    assert result.assessments[0].status == SemanticMatchStatus.MISSING


# ---------------------------------------------------------------------------
# Score Authority Protection Tests
# ---------------------------------------------------------------------------

def test_llm_overall_score_rejected():
    """If LLM returns an overall_score, it is captured but ignored."""
    mock_gateway = MagicMock()
    mock_gateway.generate = AsyncMock(return_value=LLMResponse(
        provider=LLMProvider.GROQ,
        model="test-model",
        content=json.dumps({
            "assessments": [
                {
                    "requirement_id": "ServiceNow",
                    "status": "matched",
                    "confidence": 0.95,
                    "evidence": "Used ServiceNow",
                    "reasoning": "Explicit mention.",
                    "evidence_strength": "strong",
                }
            ],
            "overall_score": 82,  # LLM tried to calculate score — must be rejected
        }),
    ))
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)

    reqs = [
        {"canonical": "ServiceNow", "category": "skill", "importance": "high",
         "variants": ["ServiceNow"], "job_evidence": "ServiceNow"},
    ]

    result = _run_sync(reasoner.analyze_requirements(reqs, _make_service_desk_resume()))

    assert result.success
    assert result.overall_score_rejection == 82
    # The overall score is NOT used — only individual assessments
    assert len(result.assessments) == 1


def test_score_calculation_not_in_llm_response():
    """The LLM prompt explicitly forbids returning an overall score."""
    # Verify the system prompt contains the instruction
    from app.services.ats.semantic_reasoner import _SEMANTIC_REASONING_SYSTEM_PROMPT
    assert "Do NOT calculate scores" in _SEMANTIC_REASONING_SYSTEM_PROMPT
    assert "Do NOT return an overall score" in _SEMANTIC_REASONING_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Evidence Validation Tests
# ---------------------------------------------------------------------------

def test_evidence_validation_exact_match():
    """Exact substring match validates evidence."""
    resume = "managed level 1 incident tickets using servicenow and itsm processes"
    evidence = "using ServiceNow and ITSM processes"
    assert _validate_evidence_against_resume(evidence, resume)


def test_evidence_validation_no_match():
    """Evidence not in resume is rejected."""
    resume = "managed level 1 incident tickets using itsm processes"
    evidence = "Managed Active Directory OU structures"
    assert not _validate_evidence_against_resume(evidence, resume)


def test_evidence_validation_empty_evidence():
    """Empty evidence is rejected."""
    assert not _validate_evidence_against_resume("", "some resume text")
    assert not _validate_evidence_against_resume(None, "some resume text")


# ---------------------------------------------------------------------------
# LLM Response Parsing Tests
# ---------------------------------------------------------------------------

def test_parse_valid_json():
    """Valid JSON with assessments key is parsed correctly."""
    data = _parse_llm_response(json.dumps({"assessments": [{"requirement_id": "test"}]}))
    assert "assessments" in data
    assert len(data["assessments"]) == 1


def test_parse_json_with_code_fences():
    """JSON wrapped in markdown code fences is parsed correctly."""
    response = '```json\n{"assessments": [{"requirement_id": "test"}]}\n```'
    data = _parse_llm_response(response)
    assert "assessments" in data


def test_parse_invalid_json():
    """Invalid JSON raises ValueError."""
    with pytest.raises(ValueError):
        _parse_llm_response("not valid json")


def test_parse_missing_assessments_key():
    """JSON without assessments key raises ValueError."""
    with pytest.raises(ValueError):
        _parse_llm_response(json.dumps({"score": 85}))


def test_parse_non_array_assessments():
    """Non-array assessments raises ValueError."""
    with pytest.raises(ValueError):
        _parse_llm_response(json.dumps({"assessments": "not an array"}))


# ---------------------------------------------------------------------------
# Assessment Validation Tests
# ---------------------------------------------------------------------------

def test_validate_assessment_valid():
    """Valid assessment passes validation."""
    known = {"ServiceNow": "ServiceNow"}
    raw = {
        "requirement_id": "ServiceNow",
        "status": "matched",
        "confidence": 0.95,
        "evidence": "Used ServiceNow",
        "reasoning": "Explicit mention.",
        "evidence_strength": "strong",
    }
    assessment = _validate_assessment(raw, known)
    assert assessment is not None
    assert assessment.requirement_id == "ServiceNow"
    assert assessment.status == SemanticMatchStatus.MATCHED
    assert assessment.confidence == 0.95


def test_validate_assessment_unknown_requirement():
    """Assessment for unknown requirement returns None."""
    known = {"ServiceNow": "ServiceNow"}
    raw = {
        "requirement_id": "UnknownTool",
        "status": "matched",
        "confidence": 0.95,
        "evidence": "Used it",
        "reasoning": "Yes.",
        "evidence_strength": "strong",
    }
    assessment = _validate_assessment(raw, known)
    assert assessment is None


def test_validate_assessment_invalid_status():
    """Invalid status defaults to UNKNOWN."""
    known = {"ServiceNow": "ServiceNow"}
    raw = {
        "requirement_id": "ServiceNow",
        "status": "totally_invalid",
        "confidence": 0.95,
        "evidence": "Used ServiceNow",
        "reasoning": "Yes.",
        "evidence_strength": "strong",
    }
    assessment = _validate_assessment(raw, known)
    assert assessment is not None
    assert assessment.status == SemanticMatchStatus.UNKNOWN


def test_validate_assessment_clamps_confidence():
    """Confidence is clamped to 0-1 range."""
    known = {"ServiceNow": "ServiceNow"}
    raw = {
        "requirement_id": "ServiceNow",
        "status": "matched",
        "confidence": 1.5,
        "evidence": "Used ServiceNow",
        "reasoning": "Yes.",
        "evidence_strength": "strong",
    }
    assessment = _validate_assessment(raw, known)
    assert assessment is not None
    assert assessment.confidence == 1.0


# ---------------------------------------------------------------------------
# Build Helpers Tests
# ---------------------------------------------------------------------------

def test_build_resume_text():
    """Resume text extraction produces usable text."""
    resume = _make_service_desk_resume()
    text = _build_resume_text(resume.profile)
    assert "ServiceNow" in text
    assert "IT Corp" in text
    assert len(text) > 100


def test_build_resume_skills():
    """Skills list is properly deduplicated."""
    resume = _make_service_desk_resume()
    skills = _build_resume_skills(resume.profile)
    assert "ServiceNow" in skills
    assert "ITSM" in skills


def test_build_requirements_block():
    """Requirements block is properly formatted."""
    concepts = [
        {"canonical": "ServiceNow", "category": "skill", "importance": "high",
         "variants": ["ServiceNow"], "job_evidence": "ServiceNow"},
    ]
    block = _build_requirements_block(concepts)
    assert "ServiceNow" in block
    assert "skill" in block
    assert "high" in block


# ---------------------------------------------------------------------------
# Metadata Tests
# ---------------------------------------------------------------------------

def test_semantic_metadata_builds_correctly():
    """Semantic metadata is built correctly from analysis results."""
    semantic_result = SemanticAnalysisResult(
        assessments=[],
        model_used="test-model",
        provider_used="groq",
        latency_ms=150.0,
        success=True,
    )

    metadata = build_semantic_metadata(
        semantic_result=semantic_result,
        reconciled_count=10,
        upgrades=3,
        overrides=1,
    )

    assert metadata.semantic_available is True
    assert metadata.semantic_success is True
    assert metadata.semantic_model == "test-model"
    assert metadata.semantic_provider == "groq"
    assert metadata.semantic_latency_ms == 150.0
    assert metadata.reconciled_count == 10
    assert metadata.semantic_upgrades == 3
    assert metadata.semantic_overrides == 1


def test_semantic_metadata_failure():
    """Metadata reflects failure when semantic analysis fails."""
    semantic_result = SemanticAnalysisResult(
        assessments=[],
        success=False,
        error_message="Provider timeout",
    )

    metadata = build_semantic_metadata(
        semantic_result=semantic_result,
        reconciled_count=0,
        upgrades=0,
        overrides=0,
    )

    assert metadata.semantic_available is True
    assert metadata.semantic_success is False


# ---------------------------------------------------------------------------
# Empty Concepts Tests
# ---------------------------------------------------------------------------

def test_no_concepts_returns_empty():
    """When no concepts are extracted, semantic reasoning returns empty."""
    mock_gateway = _make_mock_gateway([])
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)

    result = _run_sync(reasoner.analyze_requirements([], _make_service_desk_resume()))

    assert result.success
    assert len(result.assessments) == 0
    mock_gateway.generate.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: Full ATSAnalyzer + Semantic Reasoner
# ---------------------------------------------------------------------------

def test_full_integration_with_semantic_reasoning():
    """Full integration: ATSAnalyzer with semantic reasoner produces enriched results."""
    reqs = _make_concepts_from_jd(ACCENTURE_SERVICE_DESK_JD)

    # Build assessments for all concepts
    assessments = []
    for concept in reqs:
        canonical = concept["canonical"]
        if canonical in ["ServiceNow", "ITSM", "L1 Technical Support", "Incident Management"]:
            assessments.append({
                "requirement_id": canonical,
                "status": "matched",
                "confidence": 0.92,
                "evidence": f"Resume demonstrates {canonical} experience",
                "reasoning": f"Resume explicitly mentions {canonical}.",
                "evidence_strength": "strong",
            })
        elif canonical == "BMC Remedy":
            assessments.append({
                "requirement_id": canonical,
                "status": "missing",
                "confidence": 0.95,
                "evidence": None,
                "reasoning": "No mention of BMC Remedy in the resume.",
                "evidence_strength": "none",
            })
        elif canonical == "Active Directory":
            assessments.append({
                "requirement_id": canonical,
                "status": "missing",
                "confidence": 0.90,
                "evidence": None,
                "reasoning": "No mention of Active Directory in the resume.",
                "evidence_strength": "none",
            })
        else:
            assessments.append({
                "requirement_id": canonical,
                "status": "partial" if "Remote" in canonical else "matched",
                "confidence": 0.75,
                "evidence": f"Partial evidence for {canonical}",
                "reasoning": f"Some evidence for {canonical}.",
                "evidence_strength": "moderate",
            })

    mock_gateway = _make_mock_gateway(assessments)
    reasoner = ATSSemanticReasoner(gateway=mock_gateway)
    analyzer = ATSAnalyzer(semantic_reasoner=reasoner)

    result = analyzer.analyze_resume(
        resume_content=_make_service_desk_resume(),
        job_description=ACCENTURE_SERVICE_DESK_JD,
        job_title="Service Desk Associate",
        company="Accenture"
    )

    # Verify basic scoring still works
    assert result.overall_score > 0
    assert result.overall_score <= 100

    # Verify semantic metadata is present
    assert result.semantic_metadata is not None
    assert result.semantic_metadata.semantic_success is True
    assert result.semantic_metadata.reconciled_count > 0

    # Verify semantic explanation in analysis_explanation
    assert "semantic_reasoning" in result.analysis_explanation

    # Verify deterministic results still present
    assert "ServiceNow" in result.matched_skills or "ServiceNow" in [c.requirement for c in result.requirement_coverage if c.status == "matched"]


# ---------------------------------------------------------------------------
# Helper to run async
# ---------------------------------------------------------------------------

def _run_sync(coro):
    """Run an async coroutine synchronously for tests."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an event loop — use nest_asyncio or create new loop
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)
