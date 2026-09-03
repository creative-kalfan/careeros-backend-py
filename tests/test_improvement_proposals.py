"""Tests for Evidence-Grounded Resume Improvement Engine (Target 5.3).

Covers:
1. Single batched LLM call verification.
2. Anti-hallucination guardrails & ungrounded metric detection.
3. Metric question generation (metrics_prompt instead of inventing numbers).
4. Provenance lock (projects remain projects; never promoted to professional work).
5. Fresher project improvements without scope inflation.
7. Deterministic fallback on LLM failure or invalid response.
8. Zero ATS score mutation guarantee.
"""

from __future__ import annotations

import json
import pytest
from typing import List
from unittest.mock import AsyncMock, MagicMock

from app.llm import LLMGateway, LLMResponse, LLMTask, LLMProvider, LLMProviderError
from app.models.resume import ResumeContent, ResumeProfile, ProjectItem, ExperienceItem, SkillCategory
from app.models.ats import (
    EvidenceLevel,
    JobRequirementType,
    RequirementCoverage,
    ATSAnalysisReport,
    ATSAnalysisResult,
)
from app.models.improvement import (
    ImprovementClassification,
    ImprovementProposal,
    ImprovementAssessment,
    ImprovementBatchResult,
)
from app.services.improvement.improvement_service import (
    ResumeImprovementService,
    detect_unverified_metrics,
    enforce_provenance_lock,
)


def _cov(
    requirement: str = "Docker",
    status: str = "partial",
    category: str = "skill",
    importance: str = "high",
    resume_evidence: List[str] = None,
    evidence_source_section: str = "projects[0]",
) -> RequirementCoverage:
    return RequirementCoverage(
        requirement=requirement,
        requirement_type=JobRequirementType.SKILL,
        resume_evidence=resume_evidence if resume_evidence is not None else ["Used Docker for local development."],
        evidence_level=EvidenceLevel.PARTIAL if resume_evidence else EvidenceLevel.NONE,
        evidence_source_section=evidence_source_section,
        category=category,
        importance=importance,
        status=status,
    )


# ---------------------------------------------------------------------------
# 1. Anti-Hallucination & Metric Guard
# ---------------------------------------------------------------------------


class TestMetricGuard:
    def test_ungrounded_percentage_detected_and_converted(self):
        source = ["Built a web dashboard using React and Tailwind."]
        proposed = "Developed high-performance web dashboard using React and Tailwind, improving load time by 45%."

        sanitized, prompt, flags = detect_unverified_metrics(proposed, source)

        assert "45%" not in sanitized
        assert "unverified_metric_converted_to_prompt" in flags
        assert prompt is not None
        assert "% improvement" in prompt or "metrics" in prompt.lower()

    def test_ungrounded_multiplier_detected_and_converted(self):
        source = ["Configured database queries for reporting."]
        proposed = "Optimized database queries resulting in 3x faster report generation."

        sanitized, prompt, flags = detect_unverified_metrics(proposed, source)

        assert "3x" not in sanitized
        assert "unverified_metric_converted_to_prompt" in flags
        assert prompt is not None

    def test_ungrounded_dollar_amount_detected_and_converted(self):
        source = ["Managed cloud infrastructure."]
        proposed = "Managed cloud infrastructure saving $20,000 annually."

        sanitized, prompt, flags = detect_unverified_metrics(proposed, source)

        assert "$20,000" not in sanitized
        assert "unverified_metric_converted_to_prompt" in flags
        assert prompt is not None

    def test_verified_metric_in_source_is_preserved(self):
        source = ["Reduced API latency by 35% using Redis caching."]
        proposed = "Leveraged Redis caching to reduce API latency by 35% across all endpoints."

        sanitized, prompt, flags = detect_unverified_metrics(proposed, source)

        assert "35%" in sanitized
        assert "unverified_metric_converted_to_prompt" not in flags

    def test_general_metric_prompt_for_unquantified_bullet(self):
        source = ["Wrote unit tests for authentication module."]
        proposed = "Implemented comprehensive unit tests for authentication module using pytest."

        sanitized, prompt, flags = detect_unverified_metrics(proposed, source)

        assert sanitized == proposed
        assert prompt is not None
        assert "quantifiable metrics" in prompt.lower() or "scale" in prompt.lower()


# ---------------------------------------------------------------------------
# 2. Provenance Lock
# ---------------------------------------------------------------------------


class TestProvenanceLock:
    def test_project_cannot_be_promoted_to_experience(self):
        prov, sec, flags = enforce_provenance_lock(
            provenance="project",
            target_section="experience",
            proposed_wording="Led backend architecture for project.",
        )
        assert prov == "project"
        assert sec == "projects"
        assert "provenance_lock_applied" in flags

    def test_academic_cannot_be_promoted_to_professional(self):
        prov, sec, flags = enforce_provenance_lock(
            provenance="academic",
            target_section="professional",
            proposed_wording="Built compiler in coursework.",
        )
        assert prov == "academic"
        assert sec == "academics"
        assert "provenance_lock_applied" in flags

    def test_professional_provenance_allowed_in_experience(self):
        prov, sec, flags = enforce_provenance_lock(
            provenance="professional",
            target_section="experience",
            proposed_wording="Maintained production service.",
        )
        assert prov == "professional"
        assert sec == "experience"
        assert len(flags) == 0


# ---------------------------------------------------------------------------
# 3. Deterministic Proposal Generation
# ---------------------------------------------------------------------------


class TestDeterministicProposals:
    def test_generates_grounded_proposal_for_weak_evidence(self):
        service = ResumeImprovementService()
        cov = _cov(
            requirement="Kubernetes",
            status="partial",
            resume_evidence=["Deployed microservices to local Kubernetes cluster."],
            evidence_source_section="projects[0]",
        )

        assessment = service.build_deterministic_assessment(cov)

        assert assessment.requirement_id == "Kubernetes"
        assert assessment.classification == ImprovementClassification.PRESENT_BUT_UNDERREPRESENTED
        assert len(assessment.proposals) == 1

        prop = assessment.proposals[0]
        assert prop.requirement_id == "Kubernetes"
        assert prop.provenance == "project"
        assert prop.target_section == "projects[0]"
        assert "Kubernetes" in prop.proposed_wording
        assert prop.metrics_prompt is not None


# ---------------------------------------------------------------------------
# 4. Batched LLM Assessment & Single Request Guarantee
# ---------------------------------------------------------------------------


class TestBatchedLLMImprovement:
    @pytest.mark.asyncio
    async def test_single_batched_llm_call_for_multiple_requirements(self):
        mock_gateway = MagicMock(spec=LLMGateway)
        mock_gateway.generate = AsyncMock(
            return_value=LLMResponse(
                content=json.dumps({
                    "assessments": [
                        {
                            "requirement_id": "Docker",
                            "classification": "present_but_weak",
                            "confidence": 0.88,
                            "proposed_wording": "Containerized backend microservices using Docker to standardize development environments.",
                            "rationale": "Clarifies purpose and impact of Docker usage.",
                            "diff_summary": "Expanded Docker bullet with containerization context.",
                            "metrics_prompt": "Did containerization speed up onboarding or testing times?",
                            "target_section": "projects",
                            "provenance": "project",
                            "safety_flags": [],
                        },
                        {
                            "requirement_id": "TypeScript",
                            "classification": "present_but_weak",
                            "confidence": 0.90,
                            "proposed_wording": "Built type-safe frontend components in TypeScript.",
                            "rationale": "Directly highlights TypeScript type safety.",
                            "diff_summary": "Emphasized type-safe development.",
                            "metrics_prompt": None,
                            "target_section": "projects",
                            "provenance": "project",
                            "safety_flags": [],
                        },
                    ]
                }),
                provider=LLMProvider.GROQ,
                model="mock-model",
            )
        )

        service = ResumeImprovementService(gateway=mock_gateway)
        covs = [
            _cov("Docker", resume_evidence=["Used Docker."]),
            _cov("TypeScript", resume_evidence=["Wrote TypeScript frontend."]),
            _cov("AWS", status="missing", resume_evidence=[]),
        ]
        resume_content = ResumeContent(
            profile=ResumeProfile(
                projects=[
                    ProjectItem(
                        name="Portfolio",
                        description="Personal portfolio site",
                        technologies=["Docker", "TypeScript"],
                    )
                ]
            )
        )

        result = await service.assess(
            coverage=covs,
            resume_content=resume_content,
            job_title="Software Engineer",
            company="Tech Corp",
        )

        # EXACTLY 1 call to LLMGateway for all requirements
        assert mock_gateway.generate.call_count == 1
        call_args = mock_gateway.generate.call_args[0][0]
        assert call_args.task == LLMTask.RESUME_IMPROVEMENT_ASSESSMENT

        assert result.success is True
        assert result.fallback_used is False
        assert len(result.assessments) == 3

        docker_ass = next(a for a in result.assessments if a.requirement_id == "Docker")
        assert docker_ass.ai_generated is True
        assert len(docker_ass.proposals) == 1
        assert "Containerized backend microservices" in docker_ass.proposals[0].proposed_wording

    @pytest.mark.asyncio
    async def test_llm_hallucinated_metric_is_neutralized_in_batch(self):
        mock_gateway = MagicMock(spec=LLMGateway)
        mock_gateway.generate = AsyncMock(
            return_value=LLMResponse(
                content=json.dumps({
                    "assessments": [
                        {
                            "requirement_id": "Python",
                            "classification": "present_but_weak",
                            "confidence": 0.85,
                            "proposed_wording": "Automated ETL pipelines in Python increasing throughput by 85%.",
                            "rationale": "Emphasizes ETL automation.",
                            "diff_summary": "Added automation metric.",
                            "target_section": "projects",
                            "provenance": "project",
                            "safety_flags": [],
                        }
                    ]
                }),
                provider=LLMProvider.GROQ,
                model="mock-model",
            )
        )

        service = ResumeImprovementService(gateway=mock_gateway)
        covs = [_cov("Python", resume_evidence=["Wrote simple Python scripts for data processing."])]
        resume_content = ResumeContent()

        result = await service.assess(
            coverage=covs,
            resume_content=resume_content,
        )

        assert result.success is True
        python_ass = result.assessments[0]
        prop = python_ass.proposals[0]

        # 85% was NOT in source -> neutralized
        assert "85%" not in prop.proposed_wording
        assert "unverified_metric_converted_to_prompt" in prop.safety_flags
        assert prop.metrics_prompt is not None


# ---------------------------------------------------------------------------
# 5. Deterministic Fallback on LLM Error
# ---------------------------------------------------------------------------


class TestDeterministicFallback:
    @pytest.mark.asyncio
    async def test_fallback_on_provider_error(self):
        mock_gateway = MagicMock(spec=LLMGateway)
        mock_gateway.generate = AsyncMock(
            side_effect=LLMProviderError("Gateway timeout", provider=LLMProvider.GROQ)
        )

        service = ResumeImprovementService(gateway=mock_gateway)
        covs = [_cov("Docker", resume_evidence=["Used Docker."])]
        resume_content = ResumeContent()

        result = await service.assess(coverage=covs, resume_content=resume_content)

        assert result.success is False
        assert result.fallback_used is True
        assert len(result.assessments) == 1
        assert len(result.assessments[0].proposals) == 1
        assert result.assessments[0].proposals[0].ai_generated is False

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json_output(self):
        mock_gateway = MagicMock(spec=LLMGateway)
        mock_gateway.generate = AsyncMock(
            return_value=LLMResponse(content="Sorry, cannot process.", provider=LLMProvider.GROQ, model="m")
        )

        service = ResumeImprovementService(gateway=mock_gateway)
        covs = [_cov("Docker", resume_evidence=["Used Docker."])]
        resume_content = ResumeContent()

        result = await service.assess(coverage=covs, resume_content=resume_content)

        assert result.success is False
        assert result.fallback_used is True
        assert len(result.assessments) == 1


# ---------------------------------------------------------------------------
# 6. Zero ATS Score Mutation Guarantee
# ---------------------------------------------------------------------------


class TestZeroATSScoreMutation:
    def test_assessment_does_not_mutate_ats_report(self):
        cov = _cov(
            requirement="PostgreSQL",
            status="partial",
            resume_evidence=["Used PostgreSQL."],
            evidence_source_section="projects[0]",
        )

        initial_dict = cov.model_dump()

        service = ResumeImprovementService()
        assessment = service.build_deterministic_assessment(cov)

        # Generating proposals MUST NOT change ATS coverage properties
        assert cov.model_dump() == initial_dict
        assert len(assessment.proposals) > 0


# ---------------------------------------------------------------------------
# 7. No-Evidence Barrier Removed
# ---------------------------------------------------------------------------


class TestNoEvidenceBarrierRemoved:
    """Confirm that missing evidence NEVER blocks an improvement assessment/proposal."""

    def _no_evidence_cov(self, requirement: str = "Kubernetes") -> RequirementCoverage:
        """Coverage with zero resume evidence and no semantic evidence."""
        return RequirementCoverage(
            requirement=requirement,
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=[],
            semantic_evidence=None,
            evidence_level=EvidenceLevel.NONE,
            evidence_source_section=None,
            category="skill",
            importance="high",
            status="missing",
        )

    def test_deterministic_assessment_returns_result_with_no_evidence(self):
        """Deterministic path must return an assessment even with zero evidence."""
        service = ResumeImprovementService()
        cov = self._no_evidence_cov("Terraform")
        assessment = service.build_deterministic_assessment(cov)

        assert assessment is not None
        assert assessment.requirement_id == "Terraform"
        # Classification is NO_EVIDENCE when no resume evidence is present
        assert assessment.classification == ImprovementClassification.NO_EVIDENCE
        # Assessment returned — not blocked/None

    @pytest.mark.asyncio
    async def test_llm_proposal_accepted_with_zero_resume_evidence(self):
        """LLM proposal must NOT be nulled when resume_evidence is empty."""
        mock_gateway = MagicMock(spec=LLMGateway)
        mock_gateway.generate = AsyncMock(
            return_value=LLMResponse(
                content=json.dumps({
                    "assessments": [
                        {
                            "requirement_id": "Kubernetes",
                            "classification": "no_evidence",
                            "confidence": 0.7,
                            "proposed_wording": "Highlight your experience configuring Kubernetes clusters.",
                            "rationale": "No evidence in resume; guidance helps candidate surface relevant experience.",
                            "diff_summary": "Added guidance for Kubernetes section.",
                            "metrics_prompt": None,
                            "target_section": "projects",
                            "provenance": "project",
                            "safety_flags": [],
                        }
                    ]
                }),
                provider=LLMProvider.GROQ,
                model="mock-model",
            )
        )

        service = ResumeImprovementService(gateway=mock_gateway)
        cov = self._no_evidence_cov("Kubernetes")
        resume_content = ResumeContent()

        result = await service.assess(
            coverage=[cov],
            resume_content=resume_content,
        )

        assert result.success is True
        assert len(result.assessments) == 1
        kube = result.assessments[0]
        # proposed_wording must NOT be None — evidence gate is removed
        assert kube.proposed_wording is not None, (
            "Evidence gate still active: proposed_wording was nulled despite barrier removal"
        )
        assert "Kubernetes" in kube.proposed_wording or "kubernetes" in kube.proposed_wording.lower()

    @pytest.mark.asyncio
    async def test_batched_assess_all_no_evidence_produces_batch_result(self):
        """All-no-evidence input must still go through the LLM path and return assessments."""
        mock_gateway = MagicMock(spec=LLMGateway)
        mock_gateway.generate = AsyncMock(
            return_value=LLMResponse(
                content=json.dumps({
                    "assessments": [
                        {
                            "requirement_id": "AWS",
                            "classification": "no_evidence",
                            "confidence": 0.65,
                            "proposed_wording": "Describe your AWS experience (e.g., EC2, S3, Lambda) in relevant sections.",
                            "rationale": "No evidence found; guidance provided.",
                            "diff_summary": "Added AWS guidance.",
                            "metrics_prompt": None,
                            "target_section": "projects",
                            "provenance": "project",
                            "safety_flags": [],
                        },
                        {
                            "requirement_id": "Docker",
                            "classification": "no_evidence",
                            "confidence": 0.65,
                            "proposed_wording": "Mention any Docker containerization work in your project descriptions.",
                            "rationale": "No evidence found; guidance provided.",
                            "diff_summary": "Added Docker guidance.",
                            "metrics_prompt": None,
                            "target_section": "projects",
                            "provenance": "project",
                            "safety_flags": [],
                        },
                    ]
                }),
                provider=LLMProvider.GROQ,
                model="mock-model",
            )
        )

        service = ResumeImprovementService(gateway=mock_gateway)
        covs = [self._no_evidence_cov("AWS"), self._no_evidence_cov("Docker")]
        resume_content = ResumeContent()

        result = await service.assess(
            coverage=covs,
            resume_content=resume_content,
        )

        assert result.success is True
        assert len(result.assessments) == 2
        for a in result.assessments:
            assert a.proposed_wording is not None, (
                f"Evidence gate still active: {a.requirement_id} proposed_wording was nulled"
            )
        # LLM called exactly once
        assert mock_gateway.generate.call_count == 1

