"""LLM-Powered ATS Semantic Reasoning Layer.

Evaluates each extracted requirement against actual resume evidence using the
existing LLM Gateway. The LLM is a reasoning/evidence layer, NOT the scoring
authority. It never calculates scores, never invents candidate experience, and
never modifies the resume.

Architecture:
    Deterministic Extraction → Requirement Concepts → Deterministic Evidence
                                      ↓
                        LLM Semantic Reasoning (this module)
                                      ↓
                              Reconciliation Layer
                                      ↓
                              ATS Decision Layer (scoring)
"""

from __future__ import annotations

import json
import logging
from typing import List, Dict, Any, Optional

from app.llm import (
    LLMGateway,
    LLMRequest,
    LLMTask,
    LLMProviderError,
    get_llm_gateway,
)
from app.models.ats import (
    SemanticRequirementAssessment,
    SemanticAnalysisResult,
    SemanticMatchStatus,
    SemanticEvidenceStrength,
    RequirementCoverage,
    EvidenceLevel,
    JobRequirementType,
)
from app.models.resume import ResumeContent, ResumeProfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_SEMANTIC_REASONING_SYSTEM_PROMPT = """\
You are an ATS (Applicant Tracking System) semantic reasoning assistant.
Your job is to evaluate whether a resume provides evidence for specific job requirements.

CRITICAL RULES:
1. The RESUME is the candidate's source of truth. Never assume experience exists.
2. The JOB DESCRIPTION defines the requirements to evaluate.
3. NEVER invent candidate experience. Evidence MUST come from the resume text.
4. Distinguish MATCHED / PARTIAL / MISSING / UNKNOWN.
5. Exact wording is NOT required for semantic equivalence (e.g., "first-line technical assistance" ≈ "Level 1 technical support").
6. Similar wording is NOT enough when the technology/tool is materially different (e.g., "ITSM ticketing" ≠ "ServiceNow").
7. Return ONLY valid JSON. Do NOT calculate scores. Do NOT modify the resume.
8. For each requirement, extract the strongest relevant resume excerpt as evidence.
9. Confidence reflects how strongly the evidence supports your classification, NOT the requirement's importance.
10. Do NOT return an overall score. Only return per-requirement assessments."""

_SEMANTIC_REASONING_PROMPT_TEMPLATE = """\
Evaluate each job requirement against the resume below. Return a JSON object with key "assessments" containing an array of objects.

For each requirement, provide:
- requirement_id: the canonical name exactly as given
- status: "matched" | "partial" | "missing" | "unknown"
- confidence: 0.0-1.0 (how strongly the evidence supports your classification)
- evidence: exact resume excerpt that supports your classification, or null if missing
- reasoning: short explanation of the semantic relationship (max 2 sentences)
- evidence_strength: "strong" | "moderate" | "weak" | "none"

=== RESUME TEXT ===
{resume_text}

=== RESUME SKILLS ===
{resume_skills}

=== JOB REQUIREMENTS ===
{requirements_block}

Return ONLY valid JSON in this exact format:
{{
  "assessments": [
    {{
      "requirement_id": "...",
      "status": "matched|partial|missing|unknown",
      "confidence": 0.0-1.0,
      "evidence": "...",
      "reasoning": "...",
      "evidence_strength": "strong|moderate|weak|none"
    }}
  ]
}}"""


def _build_resume_text(profile: ResumeProfile) -> str:
    """Extract all textual content from a resume for the LLM prompt."""
    parts = []

    if profile.personal:
        p = profile.personal
        parts.extend([p.full_name or "", p.headline or "", p.location or ""])

    if profile.summary:
        parts.append(profile.summary)

    for exp in profile.experience:
        parts.extend([exp.company or "", exp.role or "", exp.location or "", exp.metrics or ""])
        parts.extend(exp.get_responsibility_texts())
        parts.extend(exp.achievements)
        parts.extend(exp.tools)

    for intern in profile.internships:
        parts.extend([intern.company or "", intern.role or "", intern.location or "", intern.metrics or ""])
        parts.extend(intern.get_responsibility_texts())
        parts.extend(intern.achievements)
        parts.extend(intern.tools)

    for edu in profile.education:
        parts.extend([edu.institution or "", edu.degree or "", edu.field or ""])
        parts.extend(edu.coursework)
        parts.extend(edu.achievements)

    s = profile.skills
    if s:
        parts.extend(s.technical)
        parts.extend(s.tools)
        parts.extend(s.languages)
        parts.extend(s.databases)
        parts.extend(s.analytics)
        parts.extend(s.soft_skills)
        for cat, custom_list in s.custom.items():
            parts.extend(custom_list)

    for proj in profile.projects:
        parts.extend([proj.name or "", proj.description or "", proj.problem or "", proj.contribution or "", proj.results or "", proj.metrics or ""])
        parts.extend(proj.technologies)

    for cert in profile.certifications:
        parts.extend([cert.name or "", cert.issuer or ""])

    parts.extend(profile.achievements)

    for lead in profile.leadership:
        parts.extend([lead.organization or "", lead.role or "", lead.description or ""])

    for lang in profile.languages:
        parts.extend([lang.language or "", lang.proficiency or ""])

    for add in profile.additional:
        parts.extend([add.title or "", add.description or ""])

    return " ".join([p for p in parts if p]).strip()


def _build_resume_skills(profile: ResumeProfile) -> str:
    """Build a comma-separated skills list for the LLM prompt."""
    skills = []
    s = profile.skills
    if s:
        skills.extend(s.technical)
        skills.extend(s.tools)
        skills.extend(s.languages)
        skills.extend(s.databases)
        skills.extend(s.analytics)
        skills.extend(s.soft_skills)
        for cat, custom_list in s.custom.items():
            skills.extend(custom_list)

    # Also include tools from experience/projects
    for exp in profile.experience + profile.internships:
        skills.extend(exp.tools)
    for proj in profile.projects:
        skills.extend(proj.technologies)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for skill in skills:
        sl = skill.strip().lower()
        if sl and sl not in seen:
            seen.add(sl)
            unique.append(skill.strip())

    return ", ".join(unique) if unique else "None listed"


def _build_requirements_block(concepts: List[Dict[str, Any]]) -> str:
    """Build a numbered requirements block for the LLM prompt."""
    lines = []
    for i, concept in enumerate(concepts, 1):
        canonical = concept["canonical"]
        category = concept.get("category", "unknown")
        importance = concept.get("importance", "medium")
        job_evidence = concept.get("job_evidence", "")
        lines.append(
            f"{i}. Requirement: {canonical}\n"
            f"   Category: {category}\n"
            f"   Importance: {importance}\n"
            f"   JD evidence: {job_evidence}"
        )
    return "\n\n".join(lines) if lines else "No requirements to evaluate."


def _parse_llm_response(response_text: str) -> Dict[str, Any]:
    """Parse and validate LLM JSON response, rejecting malformed output."""
    # Strip any markdown code fences
    text = response_text.strip()
    if text.startswith("```"):
        # Remove opening fence
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")

    if "assessments" not in data:
        raise ValueError("LLM response missing required 'assessments' key")

    assessments = data["assessments"]
    if not isinstance(assessments, list):
        raise ValueError("'assessments' must be an array")

    return data


def _validate_assessment(raw: Dict[str, Any], known_requirements: Dict[str, str]) -> Optional[SemanticRequirementAssessment]:
    """Validate a single raw assessment dict against known requirements."""
    req_id = raw.get("requirement_id", "")
    if not req_id:
        return None

    # Validate requirement_id matches a known concept
    if req_id not in known_requirements:
        logger.debug("LLM returned assessment for unknown requirement: %s", req_id)
        return None

    # Validate status
    status_str = raw.get("status", "").lower()
    try:
        status = SemanticMatchStatus(status_str)
    except ValueError:
        status = SemanticMatchStatus.UNKNOWN

    # Validate confidence
    confidence = raw.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)):
        confidence = 0.0
    confidence = max(0.0, min(1.0, float(confidence)))

    # Validate evidence strength
    strength_str = raw.get("evidence_strength", "none").lower()
    try:
        evidence_strength = SemanticEvidenceStrength(strength_str)
    except ValueError:
        evidence_strength = SemanticEvidenceStrength.NONE

    # Validate evidence
    evidence = raw.get("evidence")
    if evidence and not isinstance(evidence, str):
        evidence = None
    # Truncate overly long evidence
    if evidence and len(evidence) > 500:
        evidence = evidence[:500]

    # Validate reasoning
    reasoning = raw.get("reasoning", "")
    if not isinstance(reasoning, str):
        reasoning = ""
    # Truncate overly long reasoning
    if len(reasoning) > 300:
        reasoning = reasoning[:300]

    return SemanticRequirementAssessment(
        requirement_id=req_id,
        status=status,
        confidence=confidence,
        evidence=evidence,
        reasoning=reasoning,
        evidence_strength=evidence_strength,
    )


class ATSSemanticReasoner:
    """LLM-powered semantic reasoning layer for ATS analysis.

    Evaluates each extracted requirement against resume evidence. Does NOT
    calculate scores. The deterministic engine remains the scoring authority.
    """

    def __init__(self, gateway: Optional[LLMGateway] = None, timeout_seconds: float = 30.0):
        self._gateway = gateway
        self._timeout_seconds = timeout_seconds

    def _get_gateway(self) -> LLMGateway:
        if self._gateway is None:
            self._gateway = get_llm_gateway()
        return self._gateway

    async def analyze_requirements(
        self,
        concepts: List[Dict[str, Any]],
        resume_content: ResumeContent,
        deterministic_coverage: Optional[List[RequirementCoverage]] = None,
    ) -> SemanticAnalysisResult:
        """Run semantic analysis on all requirements against the resume.

        Args:
            concepts: List of concept dicts from JobDescriptionParser.extract_job_concepts()
            resume_content: Full resume content
            deterministic_coverage: Optional existing deterministic coverage for context

        Returns:
            SemanticAnalysisResult with per-requirement assessments
        """
        if not concepts:
            return SemanticAnalysisResult(
                assessments=[],
                success=True,
            )

        profile = resume_content.profile
        resume_text = _build_resume_text(profile)
        resume_skills = _build_resume_skills(profile)
        requirements_block = _build_requirements_block(concepts)

        prompt = _SEMANTIC_REASONING_PROMPT_TEMPLATE.format(
            resume_text=resume_text[:3000],  # Truncate to control token usage
            resume_skills=resume_skills,
            requirements_block=requirements_block,
        )

        try:
            gateway = self._get_gateway()
            response = await gateway.generate(
                LLMRequest(
                    task=LLMTask.ATS_SEMANTIC_REASONING,
                    prompt=prompt,
                    system_instruction=_SEMANTIC_REASONING_SYSTEM_PROMPT,
                    temperature=0.1,  # Low temperature for consistent reasoning
                    max_tokens=2048,
                    metadata={"context": "ats_semantic_reasoning"},
                )
            )
        except LLMProviderError as exc:
            logger.warning("LLM semantic reasoning failed: %s", exc)
            return SemanticAnalysisResult(
                assessments=[],
                success=False,
                error_message=str(exc),
            )
        except Exception as exc:
            logger.error("Unexpected error in LLM semantic reasoning: %s", exc, exc_info=True)
            return SemanticAnalysisResult(
                assessments=[],
                success=False,
                error_message=f"Unexpected error: {exc}",
            )

        # Parse response
        try:
            raw_data = _parse_llm_response(response.content)
        except ValueError as exc:
            logger.warning("LLM semantic reasoning returned invalid JSON: %s", exc)
            return SemanticAnalysisResult(
                assessments=[],
                success=False,
                error_message=f"Invalid LLM response: {exc}",
            )

        # Build lookup of known requirement canonical names
        known_requirements = {c["canonical"]: c["canonical"] for c in concepts}

        # Validate and build assessments
        assessments: List[SemanticRequirementAssessment] = []
        for raw in raw_data["assessments"]:
            assessment = _validate_assessment(raw, known_requirements)
            if assessment is not None:
                assessments.append(assessment)

        # Check for rejected overall_score
        overall_score_rejection = None
        if "overall_score" in raw_data:
            overall_score_rejection = raw_data["overall_score"]
            logger.info("LLM returned overall_score=%s — rejected per architecture rules", overall_score_rejection)

        return SemanticAnalysisResult(
            assessments=assessments,
            model_used=response.model,
            provider_used=response.provider.value,
            latency_ms=response.latency_ms,
            success=True,
            overall_score_rejection=overall_score_rejection,
        )
