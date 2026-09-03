"""Resume Improvement Service (Target 5.1).

Evidence-gathering engine that produces truthful per-requirement improvement
intelligence. It NEVER manufactures experience, companies, jobs, metrics or
tools. It reuses the existing LLMGateway / ProviderRouter for the single
batched improvement call and falls back to deterministic classification when
the LLM is unavailable.

This module only assesses — it never rewrites the resume.
"""

from __future__ import annotations

import json
import logging
from typing import List, Dict, Any, Optional, Sequence

from app.llm import (
    LLMGateway,
    LLMRequest,
    LLMTask,
    LLMProviderError,
    get_llm_gateway,
)
from app.models.resume import ResumeContent, ResumeProfile
from app.models.ats import RequirementCoverage, ATSAnalysisResult
from app.models.improvement import (
    ImprovementAssessment,
    ImprovementBatchResult,
    ImprovementClassification,
    ImprovementProposal,
    EvidenceType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Evidence provenance helpers
# ---------------------------------------------------------------------------

_EVIDENCE_TYPE_BY_SECTION = {
    "experience": EvidenceType.PROFESSIONAL,
    "internships": EvidenceType.INTERNSHIP,
    "projects": EvidenceType.PROJECT,
    "education": EvidenceType.ACADEMIC,
    "certifications": EvidenceType.CERTIFICATION,
    "achievements": EvidenceType.ACHIEVEMENT,
}


def classify_evidence_type(evidence_source_section: Optional[str]) -> Optional[EvidenceType]:
    """Truthful evidence provenance from the Target 4.1 section path."""
    if not evidence_source_section:
        return None
    base = (evidence_source_section.split("[")[0] or "").strip().lower()
    return _EVIDENCE_TYPE_BY_SECTION.get(base, EvidenceType.RESUME)


# ---------------------------------------------------------------------------
# Deterministic classification (no LLM)
# ---------------------------------------------------------------------------


def classify_requirement_deterministic(
    cov: RequirementCoverage,
) -> tuple[ImprovementClassification, bool]:
    """Classify a requirement deterministically from coverage + evidence.

    Returns (classification, has_evidence). No LLM involved.
    """
    status = (cov.status or "").lower()
    evidence_level = (cov.evidence_level.value if cov.evidence_level else "").lower()
    has_evidence = bool(cov.resume_evidence or cov.semantic_evidence)
    category = (cov.category or "").lower()

    if has_evidence:
        if evidence_level in ("strong", "moderate") or status == "matched":
            return ImprovementClassification.ALREADY_STRONG, True
        if status == "partial":
            return ImprovementClassification.PRESENT_BUT_UNDERREPRESENTED, True
        return ImprovementClassification.PRESENT_BUT_WEAK, True

    # No evidence: this is a hard gap. Never route the user into an evidence
    # interview — proposals are still generated from resume/JD context alone.
    if status == "partial":
        return ImprovementClassification.NO_EVIDENCE, False
    return ImprovementClassification.NO_EVIDENCE, False


def _coverage_current_wording(cov: RequirementCoverage) -> Optional[str]:
    """Use the first verified evidence excerpt as the current wording basis."""
    for ev in cov.resume_evidence or []:
        if ev and ev.strip():
            return ev.strip()
    if cov.semantic_evidence and cov.semantic_evidence.strip():
        return cov.semantic_evidence.strip()
    return None


def _build_requirement_context(
    cov: RequirementCoverage,
    recommendation: Optional[str],
) -> Dict[str, Any]:
    return {
        "requirement_id": cov.requirement,
        "requirement": cov.requirement,
        "category": cov.category or "unknown",
        "importance": cov.importance or "unknown",
        "status": cov.status or "unknown",
        "evidence_level": cov.evidence_level.value if cov.evidence_level else "none",
        "job_evidence": cov.job_evidence,
        "existing_evidence": list(cov.resume_evidence or []) or (
            [cov.semantic_evidence] if cov.semantic_evidence else []
        ),
        "evidence_source": cov.evidence_source_section,
        "current_wording": _coverage_current_wording(cov),
        "evidence_explanation": cov.evidence_explanation,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Resume text builders (smallest sufficient context only)
# ---------------------------------------------------------------------------


def build_resume_text(profile: ResumeProfile) -> str:
    parts: List[str] = []
    p = profile.personal
    if p:
        parts.extend([p.full_name or "", p.headline or "", p.location or ""])
    if profile.summary:
        parts.append(profile.summary)
    for exp in profile.experience:
        parts.extend([exp.company or "", exp.role or ""])
        parts.extend(exp.get_responsibility_texts())
        parts.extend(exp.achievements)
        parts.extend(exp.tools)
    for intern in profile.internships:
        parts.extend([intern.company or "", intern.role or ""])
        parts.extend(intern.get_responsibility_texts())
        parts.extend(intern.tools)
    for edu in profile.education:
        parts.extend([edu.institution or "", edu.degree or "", edu.field or ""])
        parts.extend(edu.coursework)
    s = profile.skills
    if s:
        parts.extend(s.technical)
        parts.extend(s.tools)
        parts.extend(s.databases)
        parts.extend(s.analytics)
        for _, custom_list in (s.custom or {}).items():
            parts.extend(custom_list)
    for proj in profile.projects:
        parts.extend([proj.name or "", proj.description or "", proj.contribution or "", proj.metrics or ""])
        parts.extend(proj.technologies)
    for cert in profile.certifications:
        parts.extend([cert.name or "", cert.issuer or ""])
    return " ".join(str(x) for x in parts if x and str(x).strip()).strip()


def build_resume_skills(profile: ResumeProfile) -> str:
    skills: List[str] = []
    s = profile.skills
    if s:
        skills.extend(s.technical)
        skills.extend(s.tools)
        skills.extend(s.languages)
        skills.extend(s.databases)
        skills.extend(s.analytics)
        skills.extend(s.soft_skills)
        for _, custom_list in (s.custom or {}).items():
            skills.extend(custom_list)
    seen: set[str] = set()
    unique: List[str] = []
    for skill in skills:
        key = str(skill).strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(str(skill).strip())
    return ", ".join(unique) if unique else "None listed"


import re
import uuid

# ---------------------------------------------------------------------------
# Anti-hallucination & Metric Guard helpers
# ---------------------------------------------------------------------------

_METRIC_PATTERNS = [
    re.compile(r"\b\d+(?:\.\d+)?%", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?x\b", re.IGNORECASE),
    re.compile(r"\$\s*\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:k|m|million|billion))?\b", re.IGNORECASE),
    re.compile(r"\b(?:increased|reduced|boosted|saved|improved|optimized|decreased|cut|scaled)\s+by\s+\d+(?:\.\d+)?%?", re.IGNORECASE),
    re.compile(r"\b(?:handling|processed|serving|managing|supporting)\s+\d{2,}\b", re.IGNORECASE),
]


def detect_unverified_metrics(
    proposed_text: Optional[str],
    source_evidence_texts: List[str],
) -> tuple[Optional[str], Optional[str], List[str]]:
    """Detect and neutralize ungrounded metrics, converting them to metrics_prompt.

    Returns (sanitized_proposed_text, metrics_prompt, safety_flags).
    """
    if not proposed_text:
        return proposed_text, None, []

    combined_sources = " ".join(str(s) for s in source_evidence_texts if s)
    flags: List[str] = []
    sanitized = proposed_text
    invented_metric_found = False

    for pattern in _METRIC_PATTERNS:
        matches = pattern.findall(sanitized)
        for match in matches:
            match_str = match if isinstance(match, str) else str(match)
            if match_str.lower() not in combined_sources.lower():
                invented_metric_found = True
                flags.append("unverified_metric_converted_to_prompt")
                # Neutralize the invented metric from the proposed text
                # e.g., 'by 30%' -> 'substantially', '$100k' -> 'budget'
                if "%" in match_str or "by" in match_str.lower():
                    sanitized = sanitized.replace(match_str, "measurably")
                elif "$" in match_str:
                    sanitized = sanitized.replace(match_str, "budgeted resources")
                else:
                    sanitized = sanitized.replace(match_str, "significant volume")

    # Clean up any leftover double spaces
    sanitized = re.sub(r"\s+", " ", sanitized).strip()

    if invented_metric_found:
        prompt = (
            "Do you have specific metrics for this achievement (e.g. % improvement, "
            "scale/volume handled, time saved)? If so, consider adding them."
        )
        return sanitized, prompt, flags

    # If no metrics were in evidence or proposed text, provide a general metrics prompt
    has_any_metric = any(p.search(sanitized) for p in _METRIC_PATTERNS)
    if not has_any_metric:
        prompt = "Add quantifiable metrics (e.g., scale, latency reduction, volume) if known."
        return sanitized, prompt, flags

    return sanitized, None, flags


def enforce_provenance_lock(
    provenance: Optional[str],
    target_section: Optional[str],
    proposed_wording: Optional[str],
) -> tuple[str, str, List[str]]:
    """Ensure project evidence is NEVER converted into employment experience."""
    prov = (provenance or "project").strip().lower()
    sec = (target_section or f"{prov}s").strip().lower()
    flags: List[str] = []

    if prov in ("project", "academic", "internship"):
        if sec in ("experience", "professional", "work", "employment"):
            sec = f"{prov}s"
            flags.append("provenance_lock_applied")

    return prov, sec, flags


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior resume designer, career mentor, and ATS optimization specialist.
You help candidates express their REAL experience more effectively by generating improvement proposals.
You NEVER manufacture experience.

ABSOLUTE RULES (non-negotiable):
1. NEVER invent employment, companies, job titles, years of experience, responsibilities, metrics, tools, or certifications.
2. NEVER convert projects, coursework, labs, or learning into professional employment experience.
3. NEVER claim a candidate possesses a skill merely because it appears in the job description.
4. Metric Guard: If no metric exists in source evidence, DO NOT invent numbers or percentages. Instead, provide a metrics_prompt.
5. Fresher / Provenance Lock: Project evidence remains Project, Internship remains Internship, Academic remains Academic.
6. You MAY generate proposed_wording for any requirement — even when resume evidence is absent — as long as you do not invent facts. Use improvement language such as 'Describe your experience with X' or 'Highlight your work on Y' when evidence is missing.
7. Output clear diff_summary, rationale, target_section, and provenance for each proposal."""

_PROMPT_TEMPLATE = """\
For each job requirement below, produce an improvement assessment and proposal.

TARGET ROLE: {job_title}
TARGET COMPANY: {company}

Return a JSON object with key "assessments" — an array of one object per requirement:
- requirement_id: the exact requirement id given
- classification: "already_strong" | "present_but_weak" | "present_but_underrepresented" | "no_evidence"
- confidence: 0.0-1.0
- proposed_wording: improved wording grounded ONLY in the given evidence and your resume-design expertise. Even when resume evidence is absent you produce truthful, useful wording (e.g. a prompt to highlight relevant project work) — never return null merely because evidence is missing.
- rationale: short user-safe explanation (max 2 sentences)
- diff_summary: concise explanation of what was clarified or emphasized
- metrics_prompt: question asking for real metrics if none exist in evidence, or null
- target section (e.g. "projects", "experience", "skills")
- provenance: truthful provenance (e.g. "project", "internship", "professional", "academic")
- safety_flags: array of strings if any guardrail was triggered

=== CANDIDATE RESUME SNIPPET ===
{resume_snippet}

=== CANDIDATE SKILLS ===
{resume_skills}

=== REQUIREMENTS TO ASSESS ===
{requirements_block}

Return ONLY valid JSON:
{{
  "assessments": [
    {{
      "requirement_id": "...",
      "classification": "present_but_weak",
      "confidence": 0.85,
      "proposed_wording": "...",
      "rationale": "...",
      "diff_summary": "...",
      "metrics_prompt": "... or null",
      "target_section": "projects",
      "provenance": "project",
      "safety_flags": []
    }}
  ]
}}"""


def _build_requirements_block(contexts: List[Dict[str, Any]]) -> str:
    lines = []
    for i, ctx in enumerate(contexts, start=1):
        evidence = "; ".join(ctx.get("existing_evidence", [])) or "none"
        lines.append(f"{i}. id={ctx['requirement_id']}")
        lines.append(f"   requirement: {ctx['requirement']}")
        lines.append(f"   category: {ctx['category']}")
        lines.append(f"   importance: {ctx['importance']}")
        lines.append(f"   status: {ctx['status']}")
        lines.append(f"   provenance: {ctx.get('provenance') or 'n/a'}")
        lines.append(f"   job_evidence: {ctx.get('job_evidence') or 'n/a'}")
        lines.append(f"   evidence_source: {ctx.get('evidence_source') or 'n/a'}")
        lines.append(f"   existing_evidence: {evidence}")
        lines.append(f"   current_wording: {ctx.get('current_wording') or 'n/a'}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ResumeImprovementService:
    """Evidence-grounded improvement intelligence engine (Target 5.3)."""

    def __init__(self, gateway: Optional[LLMGateway] = None) -> None:
        self._gateway = gateway

    def _get_gateway(self) -> LLMGateway:
        if self._gateway is None:
            self._gateway = get_llm_gateway()
        return self._gateway

    def _evidence_type(self, cov: RequirementCoverage) -> Optional[EvidenceType]:
        return classify_evidence_type(cov.evidence_source_section)

    def _recommendation_for(self, analysis: Optional[ATSAnalysisResult], requirement: str) -> Optional[str]:
        if not analysis:
            return None
        for group in (
            analysis.high_priority_recommendations,
            analysis.medium_priority_recommendations,
            analysis.low_priority_recommendations,
        ):
            for rec in group or []:
                if requirement and requirement.lower() in (rec or "").lower():
                    return rec
        return None

    def build_deterministic_assessment(
        self,
        cov: RequirementCoverage,
        analysis: Optional[ATSAnalysisResult] = None,
    ) -> ImprovementAssessment:
        """Build deterministic improvement assessment and proposal without LLM."""
        classification, has_evidence = classify_requirement_deterministic(cov)
        evidence_type = self._evidence_type(cov)
        existing_ev = list(cov.resume_evidence or []) or ([cov.semantic_evidence] if cov.semantic_evidence else [])
        current_w = _coverage_current_wording(cov)

        proposals: List[ImprovementProposal] = []
        proposed_wording: Optional[str] = None
        safety_flags: List[str] = []

        # Resume-based evidence proposal
        if has_evidence and classification in (
            ImprovementClassification.PRESENT_BUT_WEAK,
            ImprovementClassification.PRESENT_BUT_UNDERREPRESENTED,
        ):
            prov = (evidence_type.value if evidence_type else "resume").lower()
            sec = cov.evidence_source_section or f"{prov}s"
            curr_excerpt = current_w or cov.requirement

            # Cleanly construct improved wording highlighting requirement
            if curr_excerpt.lower().startswith(cov.requirement.lower()):
                proposed_text = curr_excerpt
            else:
                proposed_text = f"Applied {cov.requirement} to {curr_excerpt[0].lower() + curr_excerpt[1:] if len(curr_excerpt) > 1 else curr_excerpt}"

            sanitized_text, metrics_prompt, m_flags = detect_unverified_metrics(proposed_text, existing_ev)
            prov_clean, sec_clean, p_flags = enforce_provenance_lock(prov, sec, sanitized_text)
            all_flags = m_flags + p_flags

            proposal = ImprovementProposal(
                id=str(uuid.uuid4()),
                requirement_id=cov.requirement,
                target_section=sec_clean,
                provenance=prov_clean,
                original_text=curr_excerpt,
                proposed_wording=sanitized_text or proposed_text,
                rationale=self._deterministic_rationale(classification, cov),
                diff_summary=f"Refined phrasing for {cov.requirement} based on resume evidence.",
                metrics_prompt=metrics_prompt or "Add quantifiable metrics (e.g., scale, latency reduction, volume) if known.",
                evidence_sources=existing_ev,
                safety_flags=all_flags,
                confidence=0.8,
                ai_generated=False,
            )
            proposals.append(proposal)
            proposed_wording = proposal.proposed_wording

        return ImprovementAssessment(
            requirement_id=cov.requirement,
            classification=classification,
            confidence=0.85 if proposals else (0.8 if has_evidence else 0.7),
            existing_evidence=existing_ev,
            evidence_source=cov.evidence_source_section,
            evidence_type=evidence_type,
            current_wording=current_w,
            proposed_wording=proposed_wording,
            rationale=self._deterministic_rationale(classification, cov),
            safety_flags=safety_flags,
            ai_generated=False,
            proposals=proposals,
        )

    def _deterministic_rationale(
        self, classification: ImprovementClassification, cov: RequirementCoverage
    ) -> str:
        if classification == ImprovementClassification.ALREADY_STRONG:
            return "Your resume already supports this requirement clearly."
        if classification == ImprovementClassification.PRESENT_BUT_WEAK:
            return "Evidence exists but the wording is vague or under-specified."
        if classification == ImprovementClassification.PRESENT_BUT_UNDERREPRESENTED:
            return "Relevant evidence exists but is not clearly connected to this requirement."
        return "No evidence of this requirement was found in your resume."

    # ------------------------------------------------------------------
    # Public: batched assessment
    # ------------------------------------------------------------------

    async def assess(
        self,
        coverage: Sequence[RequirementCoverage],
        resume_content: ResumeContent,
        job_title: Optional[str] = None,
        company: Optional[str] = None,
        analysis: Optional[ATSAnalysisResult] = None,
    ) -> ImprovementBatchResult:
        """Produce improvement intelligence and proposals for the given requirements.

        Single batched LLM request using existing LLMGateway / ProviderRouter.
        Deterministic assessment always runs. LLM refinement runs in ONE
        batched call for all requirements. On LLM failure, deterministic
        assessments & proposals are returned with fallback_used=True.
        Zero ATS score mutation. Proposals are generated regardless of evidence presence.
        """
        profile = resume_content.profile if hasattr(resume_content, "profile") and resume_content.profile else ResumeProfile()
        resume_snippet = build_resume_text(profile)[:2500]
        resume_skills = build_resume_skills(profile)

        contexts: List[Dict[str, Any]] = []
        deterministic: List[ImprovementAssessment] = []

        for cov in coverage:
            if not cov.requirement:
                continue
            det = self.build_deterministic_assessment(cov, analysis)
            deterministic.append(det)

            # Build context for LLM for all requirements, allowing proposals even without evidence.
            ctx = _build_requirement_context(cov, self._recommendation_for(analysis, cov.requirement))
            ctx["provenance"] = (det.evidence_type.value if det.evidence_type else "resume")
            contexts.append(ctx)

        if not contexts:
            return ImprovementBatchResult(
                assessments=deterministic,
                success=True,
                fallback_used=False,
                message="All requirements are either strong or present no improvement angle.",
            )

        try:
            refined = await self._run_batched_llm(
                contexts=contexts,
                job_title=job_title,
                company=company,
                resume_snippet=resume_snippet,
                resume_skills=resume_skills,
            )
        except LLMProviderError as exc:
            logger.warning("Improvement LLM failed, using deterministic fallback: %s", exc)
            return ImprovementBatchResult(
                assessments=deterministic,
                success=False,
                fallback_used=True,
                message="Improvement guidance is unavailable; showing evidence classification.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected improvement error, using fallback: %s", exc, exc_info=True)
            return ImprovementBatchResult(
                assessments=deterministic,
                success=False,
                fallback_used=True,
                message="Improvement guidance failed; showing evidence classification.",
            )

        refined_map = {a.requirement_id: a for a in refined}
        merged: List[ImprovementAssessment] = []
        for det in deterministic:
            ref = refined_map.get(det.requirement_id)
            merged.append(self._merge_refined(det, ref) if ref is not None else det)

        return ImprovementBatchResult(
            assessments=merged,
            success=True,
            fallback_used=False,
            message="Improvement guidance generated.",
        )

    async def _run_batched_llm(
        self,
        contexts: List[Dict[str, Any]],
        job_title: Optional[str],
        company: Optional[str],
        resume_snippet: str,
        resume_skills: str,
    ) -> List[ImprovementAssessment]:
        prompt = _PROMPT_TEMPLATE.format(
            job_title=job_title or "Unknown role",
            company=company or "Unknown company",
            resume_snippet=resume_snippet or "No resume text available.",
            resume_skills=resume_skills,
            requirements_block=_build_requirements_block(contexts),
        )
        gateway = self._get_gateway()
        response = await gateway.generate(
            LLMRequest(
                task=LLMTask.RESUME_IMPROVEMENT_ASSESSMENT,
                prompt=prompt,
                system_instruction=_SYSTEM_PROMPT,
                temperature=0.2,
                max_tokens=2048,
                metadata={"context": "resume_improvement_assessment"},
            )
        )
        try:
            data = json.loads(response.content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

        raw_assessments = data.get("assessments", [])
        if not isinstance(raw_assessments, list):
            raise ValueError("'assessments' must be an array")

        known_contexts = {c["requirement_id"]: c for c in contexts}
        result: List[ImprovementAssessment] = []
        for raw in raw_assessments:
            if not isinstance(raw, dict):
                continue
            req_id = raw.get("requirement_id", "")
            if not req_id or req_id not in known_contexts:
                continue
            result.append(self._validate_refined(req_id, raw, known_contexts[req_id]))
        return result

    def _validate_refined(
        self,
        requirement_id: str,
        raw: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ImprovementAssessment:
        """Validate + sanitize an LLM refinement, applying strict Anti-Hallucination & Metric Guards."""
        classification = _parse_classification(raw.get("classification"))
        confidence = _clamp_float(raw.get("confidence"), 0.0, 1.0, 0.85)
        proposed = raw.get("proposed_wording")
        proposed = proposed.strip() if isinstance(proposed, str) else None
        rationale = raw.get("rationale")
        rationale = rationale.strip() if isinstance(rationale, str) else None
        diff_summary = raw.get("diff_summary")
        diff_summary = diff_summary.strip() if isinstance(diff_summary, str) else None
        metrics_prompt = raw.get("metrics_prompt")
        metrics_prompt = metrics_prompt.strip() if isinstance(metrics_prompt, str) else None
        target_section = raw.get("target_section")
        target_section = target_section.strip() if isinstance(target_section, str) else None
        provenance = raw.get("provenance") or context.get("provenance") or "project"
        provenance = provenance.strip() if isinstance(provenance, str) else "project"
        flags = _parse_str_list(raw.get("safety_flags"))

        existing_evidence = context.get("existing_evidence", [])

        # Evidence gating disabled: allow LLM proposals even without resume evidence.
        # The safety guards (metric detection and provenance lock) will still sanitize any invented content.
        # No forced nulling of 'proposed' here.

        proposals: List[ImprovementProposal] = []
        if proposed:
            # Anti-Hallucination 1: Metric Guard
            sanitized_wording, detected_prompt, metric_flags = detect_unverified_metrics(
                proposed, existing_evidence
            )
            flags.extend(metric_flags)
            if detected_prompt:
                metrics_prompt = detected_prompt

            # Anti-Hallucination 2: Provenance Lock
            prov_clean, sec_clean, prov_flags = enforce_provenance_lock(
                provenance, target_section, sanitized_wording
            )
            flags.extend(prov_flags)

            proposal = ImprovementProposal(
                id=str(uuid.uuid4()),
                requirement_id=requirement_id,
                target_section=sec_clean,
                provenance=prov_clean,
                original_text=context.get("current_wording"),
                proposed_wording=sanitized_wording or proposed,
                rationale=rationale or "Grounded improvement aligned with verified evidence.",
                diff_summary=diff_summary or f"Refined phrasing for {requirement_id}.",
                metrics_prompt=metrics_prompt,
                evidence_sources=existing_evidence,
                safety_flags=flags,
                confidence=confidence,
                ai_generated=True,
            )
            proposals.append(proposal)
            proposed = proposal.proposed_wording

        return ImprovementAssessment(
            requirement_id=requirement_id,
            classification=classification,
            confidence=confidence,
            existing_evidence=existing_evidence,
            proposed_wording=proposed,
            rationale=rationale,
            safety_flags=flags,
            ai_generated=True,
            proposals=proposals,
        )

    def _merge_refined(
        self, det: ImprovementAssessment, refined: ImprovementAssessment
    ) -> ImprovementAssessment:
        """Merge LLM refinement into the deterministic base, keeping evidence and proposals.

        Proposals are accepted regardless of evidence presence. Only metric and provenance guards remain active.
        """
        base = det.model_copy(deep=True)
        has_evidence = bool(base.existing_evidence) or bool(base.proposals)
        refined_cls = refined.classification

        # Never regress a requirement that has evidence back to an evidence-missing
        # state claimed by the LLM.
        if has_evidence and refined_cls == ImprovementClassification.NO_EVIDENCE:
            # Evidence exists — LLM misclassified to an evidence-missing state.
            refined_cls = base.classification

        base.classification = refined_cls
        base.confidence = refined.confidence
        base.ai_generated = True

        # Accept proposals regardless of evidence presence.
        if refined.proposals:
            base.proposals = refined.proposals
            base.proposed_wording = refined.proposals[0].proposed_wording
        elif refined.proposed_wording:
            base.proposed_wording = refined.proposed_wording

        if refined.rationale:
            base.rationale = refined.rationale
        if refined.safety_flags:
            base.safety_flags = refined.safety_flags
        return base


def refinement_requires_evidence(classification: ImprovementClassification) -> bool:
    """Classifications implying evidence must never be trusted without it."""
    return classification in (
        ImprovementClassification.ALREADY_STRONG,
        ImprovementClassification.PRESENT_BUT_WEAK,
        ImprovementClassification.PRESENT_BUT_UNDERREPRESENTED,
    )


def _parse_classification(value: Any) -> ImprovementClassification:
    if isinstance(value, ImprovementClassification):
        return value
    if isinstance(value, str):
        try:
            return ImprovementClassification(value.strip().lower())
        except ValueError:
            pass
    return ImprovementClassification.NO_EVIDENCE


def _clamp_float(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _parse_str_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out = []
        for v in value:
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
        return out
    return []


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_improvement_service: Optional[ResumeImprovementService] = None


def get_improvement_service() -> ResumeImprovementService:
    global _improvement_service
    if _improvement_service is None:
        _improvement_service = ResumeImprovementService()
    return _improvement_service















