"""Resume structure optimization (Stage 5b of the tailoring pipeline).

Decides section inclusion and ordering from prioritized content values —
not from fixed rules like "always include projects" or "always put skills
first". ATS compatibility constrains the output: single-column flow,
standard headings, contact completeness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.optimization.content_prioritizer import ContentScore

# Canonical section keys in document-model order (fallback when values tie).
_CANONICAL_ORDER = (
    "summary", "skills", "experience", "internships", "projects",
    "education", "certifications", "additional",
)

# Minimum aggregate value for a section to survive (avoids rendering
# near-empty sections that waste page budget and dilute relevance).
_INCLUSION_FLOOR = 0.6


@dataclass
class StructurePlan:
    section_order: List[str] = field(default_factory=list)
    included: List[str] = field(default_factory=list)
    excluded: List[str] = field(default_factory=list)
    rationale: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_order": self.section_order,
            "included": self.included,
            "excluded": self.excluded,
            "rationale": self.rationale,
        }


def _section_value(section: str, scores: List[ContentScore]) -> float:
    relevant = [s.total for s in scores if s.section == section]
    if not relevant:
        return 0.0
    # Mean of top-3 keeps long sections from dominating by volume alone.
    top = sorted(relevant, reverse=True)[:3]
    return sum(top) / len(top)


def plan_structure(
    available_sections: List[str],
    scores: List[ContentScore],
    is_fresher: bool = False,
    always_keep: Optional[List[str]] = None,
) -> StructurePlan:
    """Order available sections by aggregate content value.

    `always_keep` sections (identity-critical: summary when present,
    education, skills) are never excluded — they may only move.
    Fresher signal is a tiebreaker, not a fixed template: it nudges
    projects/education upward without forcing a rigid order.
    """
    always_keep = set(always_keep or ["summary", "education", "skills"])
    values = {sec: _section_value(sec, scores) for sec in available_sections}

    def sort_key(sec: str) -> tuple:
        value = values.get(sec, 0.0)
        fresher_boost = 0.0
        if is_fresher and sec in ("projects", "education", "internships"):
            fresher_boost = 0.35
        if not is_fresher and sec in ("experience",):
            fresher_boost = 0.35
        tiebreak = _CANONICAL_ORDER.index(sec) if sec in _CANONICAL_ORDER else 99
        return (-(value + fresher_boost), tiebreak)

    ordered = sorted(available_sections, key=sort_key)
    plan = StructurePlan(section_order=ordered)
    for sec in ordered:
        if sec in always_keep or values.get(sec, 0.0) >= _INCLUSION_FLOOR:
            plan.included.append(sec)
        else:
            plan.excluded.append(sec)
            plan.rationale.append(
                f"Excluded '{sec}': aggregate content value "
                f"({values.get(sec, 0.0):.2f}) below inclusion floor."
            )
    if not plan.excluded:
        plan.rationale.append(
            "All available sections carry sufficient value; none excluded."
        )
    return plan
