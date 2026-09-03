"""ATS Semantic Reconciliation Layer.

Merges deterministic ATS results with LLM semantic reasoning output.
Validates LLM evidence against actual resume content to prevent hallucination.
The deterministic engine remains the scoring authority.

Reconciliation rules:
1. If LLM says MATCHED with valid evidence → upgrade MISSING/PARTIAL to MATCHED
2. If LLM says MATCHED but evidence is weak/unverifiable → keep deterministic status
3. If LLM says MISSING/PARTIAL → keep it only if deterministic agrees or LLM confidence is high
4. If LLM says UNKNOWN → always fall back to deterministic
5. If LLM returns an overall_score → reject it (never trust LLM scores)
"""

from __future__ import annotations

import logging
import re
from typing import List, Dict, Any, Optional

from app.models.ats import (
    SemanticAnalysisResult,
    SemanticRequirementAssessment,
    SemanticMatchStatus,
    SemanticEvidenceStrength,
    RequirementCoverage,
    ReconciledRequirement,
    ATSAnalysisMetadata,
    JobRequirementType,
    EvidenceLevel,
)

logger = logging.getLogger(__name__)

# Confidence threshold for accepting LLM semantic upgrades
SemanticUpgradeConfidence = 0.70

# Confidence threshold for overriding deterministic classifications
SemanticOverrideConfidence = 0.85


def _validate_evidence_against_resume(
    semantic_evidence: Optional[str],
    resume_text_lower: str,
) -> bool:
    """Check whether LLM-provided evidence actually appears in the resume text.

    This is the hallucination protection gate. If the LLM fabricates evidence
    that doesn't exist in the resume, we reject the semantic assessment.
    """
    if not semantic_evidence:
        return False

    evidence_lower = semantic_evidence.lower().strip()
    if not evidence_lower:
        return False

    # Check if the evidence (or a substantial portion) appears in the resume text
    # Use a generous substring match to handle minor LLM paraphrasing
    if len(evidence_lower) > 50:
        # For longer evidence, check if at least 60% of the evidence appears
        # Split into chunks and check each
        words = evidence_lower.split()
        chunk_size = max(3, len(words) // 3)
        found_count = 0
        for i in range(0, len(words), chunk_size):
            chunk = " ".join(words[i:i + chunk_size])
            if chunk in resume_text_lower:
                found_count += 1
        total_chunks = max(1, (len(words) + chunk_size - 1) // chunk_size)
        return found_count / total_chunks >= 0.5
    else:
        # For short evidence, require exact substring match
        return evidence_lower in resume_text_lower


def _deterministic_status_from_coverage(
    coverage: RequirementCoverage,
) -> str:
    """Extract the deterministic status from a RequirementCoverage entry."""
    return coverage.status or "missing"


def reconcile_requirements(
    concept_coverage: List[RequirementCoverage],
    semantic_result: SemanticAnalysisResult,
    resume_text_lower: str,
) -> List[ReconciledRequirement]:
    """Reconcile deterministic requirement coverage with LLM semantic assessments.

    Args:
        concept_coverage: Deterministic coverage entries from ATSAnalyzer
        semantic_result: LLM semantic analysis result
        resume_text_lower: Lowercase full resume text for evidence validation

    Returns:
        List of ReconciledRequirement with final statuses
    """
    reconciled: List[ReconciledRequirement] = []

    # Build a lookup of semantic assessments by requirement_id
    semantic_lookup: Dict[str, SemanticRequirementAssessment] = {}
    for assessment in semantic_result.assessments:
        semantic_lookup[assessment.requirement_id] = assessment

    upgrades = 0
    overrides = 0

    for coverage in concept_coverage:
        canonical = coverage.requirement
        det_status = _deterministic_status_from_coverage(coverage)

        semantic = semantic_lookup.get(canonical)

        if semantic is None:
            # No LLM assessment for this requirement — use deterministic
            reconciled.append(ReconciledRequirement(
                requirement=canonical,
                requirement_type=coverage.requirement_type,
                category=coverage.category,
                importance=coverage.importance,
                deterministic_status=det_status,
                deterministic_evidence=coverage.resume_evidence[0] if coverage.resume_evidence else None,
                semantic_status=None,
                semantic_confidence=None,
                semantic_evidence=None,
                semantic_reasoning=None,
                semantic_evidence_strength=None,
                final_status=det_status,
                final_evidence=coverage.resume_evidence[0] if coverage.resume_evidence else None,
                reasoning_source="Deterministic",
            ))
            continue

        # LLM assessment exists — reconcile
        sem_status = semantic.status.value
        sem_confidence = semantic.confidence
        sem_evidence = semantic.evidence
        sem_strength = semantic.evidence_strength

        # Validate evidence against actual resume content
        evidence_valid = False
        if sem_evidence:
            if sem_status in ("matched", "partial"):
                evidence_valid = _validate_evidence_against_resume(sem_evidence, resume_text_lower)
                if not evidence_valid and sem_status == "matched":
                    logger.info(
                        "Hallucination protection: LLM claimed MATCHED for '%s' but evidence '%s' not found in resume",
                        canonical, sem_evidence[:80],
                    )
                    overrides += 1

        # Reconciliation logic
        final_status = det_status
        final_evidence = coverage.resume_evidence[0] if coverage.resume_evidence else None
        reasoning_source = "DeterministicOverride"

        if sem_status == "unknown":
            # Unknown → always fall back to deterministic
            final_status = det_status
            reasoning_source = "Deterministic"
        elif sem_status == "matched" and evidence_valid and sem_confidence >= SemanticUpgradeConfidence:
            # LLM says MATCHED with valid evidence and sufficient confidence
            if det_status == "missing":
                # Upgrade missing → matched
                final_status = "matched"
                final_evidence = sem_evidence
                reasoning_source = "LLM"
                upgrades += 1
            elif det_status == "partial":
                # Upgrade partial → matched
                final_status = "matched"
                final_evidence = sem_evidence
                reasoning_source = "LLM"
                upgrades += 1
            else:
                # Already matched — use LLM's richer evidence if available
                final_status = "matched"
                if sem_evidence:
                    final_evidence = sem_evidence
                reasoning_source = "LLM"
        elif sem_status == "matched" and evidence_valid and sem_confidence >= SemanticOverrideConfidence:
            # High confidence override even if evidence is only moderate
            if det_status == "missing":
                final_status = "matched"
                final_evidence = sem_evidence
                reasoning_source = "LLM"
                upgrades += 1
            else:
                final_status = det_status
                reasoning_source = "Deterministic"
        elif sem_status == "partial" and evidence_valid:
            # LLM says PARTIAL with valid evidence
            if det_status == "missing":
                # Upgrade missing → partial
                final_status = "partial"
                final_evidence = sem_evidence
                reasoning_source = "LLM"
            else:
                # Keep deterministic (matched > partial)
                reasoning_source = "Deterministic"
        elif sem_status == "missing":
            # LLM says MISSING — respect it if confidence is high and deterministic disagrees
            if det_status == "matched" and sem_confidence >= SemanticOverrideConfidence:
                # LLM strongly disagrees with deterministic — use LLM's assessment
                final_status = "missing"
                final_evidence = None
                reasoning_source = "LLM"
                overrides += 1
            else:
                # Otherwise, keep deterministic
                final_status = det_status
                reasoning_source = "Deterministic"
        else:
            # Fallback to deterministic
            final_status = det_status
            reasoning_source = "Deterministic"

        # Enrich coverage with semantic metadata
        reconciled.append(ReconciledRequirement(
            requirement=canonical,
            requirement_type=coverage.requirement_type,
            category=coverage.category,
            importance=coverage.importance,
            deterministic_status=det_status,
            deterministic_evidence=coverage.resume_evidence[0] if coverage.resume_evidence else None,
            semantic_status=semantic.status,
            semantic_confidence=sem_confidence,
            semantic_evidence=sem_evidence,
            semantic_reasoning=semantic.reasoning,
            semantic_evidence_strength=sem_strength,
            final_status=final_status,
            final_evidence=final_evidence,
            reasoning_source=reasoning_source,
        ))

    return reconciled, upgrades, overrides


def build_semantic_metadata(
    semantic_result: SemanticAnalysisResult,
    reconciled_count: int,
    upgrades: int,
    overrides: int,
) -> ATSAnalysisMetadata:
    """Build the metadata object for semantic reasoning in the ATS result."""
    return ATSAnalysisMetadata(
        semantic_available=True,
        semantic_success=semantic_result.success,
        semantic_model=semantic_result.model_used,
        semantic_provider=semantic_result.provider_used,
        semantic_latency_ms=semantic_result.latency_ms,
        reconciled_count=reconciled_count,
        semantic_upgrades=upgrades,
        semantic_overrides=overrides,
    )


def apply_reconciliation_to_coverage(
    concept_coverage: List[RequirementCoverage],
    reconciled: List[ReconciledRequirement],
) -> List[RequirementCoverage]:
    """Update RequirementCoverage entries with reconciled semantic results.

    Returns a new list — does not mutate the original.
    """
    reconciled_lookup = {r.requirement: r for r in reconciled}
    updated: List[RequirementCoverage] = []

    for coverage in concept_coverage:
        rec = reconciled_lookup.get(coverage.requirement)
        if rec is None:
            updated.append(coverage)
            continue

        # Create a copy with semantic fields enriched
        enriched = coverage.model_copy(deep=True)

        # Preserve original deterministic status if not already set
        if enriched.deterministic_status is None:
            enriched.deterministic_status = coverage.status

        # Update status to final reconciled status
        enriched.status = rec.final_status

        # Update evidence if LLM provided stronger evidence
        if rec.reasoning_source == "LLM" and rec.final_evidence:
            enriched.resume_evidence = [f"Semantic evidence: \"{rec.final_evidence}\""]
            enriched.evidence_level = EvidenceLevel.STRONG if rec.final_status == "matched" else EvidenceLevel.PARTIAL
            enriched.evidence_sources = ["llm_semantic"]
            # Update evidence source section from semantic evidence
            enriched.evidence_source_section = "llm_semantic"

        # Populate semantic fields
        enriched.semantic_status = rec.semantic_status
        enriched.semantic_confidence = rec.semantic_confidence
        enriched.semantic_evidence = rec.semantic_evidence
        enriched.semantic_reasoning = rec.semantic_reasoning
        enriched.semantic_evidence_strength = rec.semantic_evidence_strength
        enriched.reasoning_source = rec.reasoning_source

        # Update evidence explanation based on final status and reasoning source
        enriched.evidence_explanation = _generate_reconciled_explanation(
            requirement=rec.requirement,
            final_status=rec.final_status,
            deterministic_status=enriched.deterministic_status,
            evidence_level=enriched.evidence_level.value if enriched.evidence_level else "none",
            reasoning_source=rec.reasoning_source,
            semantic_reasoning=rec.semantic_reasoning,
            evidence_source_section=enriched.evidence_source_section,
        )

        updated.append(enriched)

    return updated


# Section descriptions for user-safe explanations
_SECTION_DESCRIPTIONS = {
    "skills": "your skills section",
    "experience": "your work experience",
    "internships": "your internship experience",
    "projects": "your projects",
    "education": "your education",
    "certifications": "your certifications",
    "summary": "your professional summary",
    "achievements": "your achievements",
    "llm_semantic": "semantic analysis of your resume",
}


def _generate_reconciled_explanation(
    requirement: str,
    final_status: str,
    deterministic_status: Optional[str],
    evidence_level: str,
    reasoning_source: str,
    semantic_reasoning: Optional[str],
    evidence_source_section: Optional[str],
) -> str:
    """Generate a user-safe explanation after reconciliation."""
    section_key = evidence_source_section.split("[")[0] if evidence_source_section else ""
    section_desc = _SECTION_DESCRIPTIONS.get(section_key, "your resume")

    if final_status == "matched":
        if reasoning_source == "LLM":
            if deterministic_status == "missing":
                base = f"Your resume contains evidence satisfying the '{requirement}' requirement, identified through semantic analysis."
            else:
                base = f"Your resume directly satisfies the '{requirement}' requirement, confirmed by semantic analysis."
        else:
            base = f"Your resume directly satisfies the '{requirement}' requirement."

        if evidence_level == "strong":
            return f"{base} The evidence is strong and found in {section_desc}."
        else:
            return f"{base} Found in {section_desc}."

    elif final_status == "partial":
        if reasoning_source == "LLM" and semantic_reasoning:
            return f"Your resume contains related evidence for '{requirement}' but does not fully satisfy the requirement. {semantic_reasoning}"
        return f"Your resume contains partial evidence for '{requirement}' found in {section_desc}, but does not fully satisfy the requirement."

    elif final_status == "missing":
        if deterministic_status == "matched" and reasoning_source == "LLM":
            return f"Semantic analysis determined that your resume does not contain sufficient evidence for '{requirement}'."
        return f"No evidence of '{requirement}' was found in your resume."

    else:
        return f"Could not determine whether '{requirement}' is present in your resume."
