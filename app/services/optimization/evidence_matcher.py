"""Evidence-to-requirement matching (Stage 3 of the tailoring pipeline).

Matches every universal JD requirement against the candidate evidence index
and assigns provenance + strength. Truthfulness rule enforced here: an
UNSUPPORTED requirement must NEVER be converted into a claimed experience —
match results carry that flag all the way to the tailoring stage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.optimization.evidence_model import (
    CandidateEvidence,
    EvidenceIndex,
    classify_requirement,
)
from app.services.optimization.jd_requirements import UniversalJD, UniversalRequirement


@dataclass
class RequirementMatch:
    requirement: UniversalRequirement
    provenance: str  # DIRECT|TRANSFERABLE|PARTIAL|UNSUPPORTED|CONFLICTING
    strength: float  # 0..1
    evidence: Optional[CandidateEvidence] = None
    # Candidate's own words supporting this requirement (for truthful reframe).
    candidate_phrasing: str = ""

    @property
    def is_claimable(self) -> bool:
        """Only DIRECT/TRANSFERABLE/PARTIAL may be surfaced in tailored copy."""
        return self.provenance in ("DIRECT", "TRANSFERABLE", "PARTIAL")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement": self.requirement.text,
            "category": self.requirement.category,
            "importance": self.requirement.importance,
            "provenance": self.provenance,
            "strength": round(self.strength, 3),
            "evidence": self.evidence.claim_text if self.evidence else None,
            "evidence_section": self.evidence.source_label if self.evidence else None,
            "claimable": self.is_claimable,
        }


@dataclass
class MatchReport:
    matches: List[RequirementMatch] = field(default_factory=list)

    @property
    def claimable(self) -> List[RequirementMatch]:
        return [m for m in self.matches if m.is_claimable]

    @property
    def supported_count(self) -> int:
        return len(self.claimable)

    @property
    def total_count(self) -> int:
        return len(self.matches)

    @property
    def has_any_overlap(self) -> bool:
        return any(m.provenance in ("DIRECT", "TRANSFERABLE") for m in self.matches)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total_count,
            "supported": self.supported_count,
            "matches": [m.to_dict() for m in self.matches],
        }


def match_requirements(
    universal_jd: UniversalJD, index: EvidenceIndex
) -> MatchReport:
    """Match every JD requirement to candidate evidence (resume-agnostic)."""
    report = MatchReport()
    for req in universal_jd.requirements:
        provenance, strength, evidence = classify_requirement(
            req.normalized_key, req.text, index
        )
        phrasing = ""
        if evidence is not None and provenance in ("DIRECT", "TRANSFERABLE", "PARTIAL"):
            phrasing = evidence.claim_text
        report.matches.append(
            RequirementMatch(
                requirement=req,
                provenance=provenance,
                strength=strength,
                evidence=evidence,
                candidate_phrasing=phrasing,
            )
        )
    return report
