"""Friendly batch evidence discovery models for universal resume tailoring.

Sits on top of the existing provenance/evidence stack
(``evidence_model`` + ``evidence_matcher``) without replacing it:

- Internally the engine still reasons in DIRECT / TRANSFERABLE / PARTIAL /
  UNSUPPORTED / CONFLICTING terms and enforces the same truthfulness rules.
- The candidate-facing layer (``to_candidate_card``) translates those
  concepts into supportive, non-accusatory language. Harsh auditor terms
  must never reach the UI.

Resume-agnostic by construction: opportunities are derived dynamically from
JD requirements + candidate evidence + semantic matching + ATS impact. No
role, industry, or vocabulary branches live here.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _gen_id() -> str:
    return uuid.uuid4().hex[:12]


def _to_camel(snake_str: str) -> str:
    components = snake_str.split("_")
    return components[0] + "".join(p.title() for p in components[1:])


class _EvidenceBase(BaseModel):
    """Accept snake_case and camelCase so API cards round-trip cleanly."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)


class ExperienceContext(str, Enum):
    """Where the candidate's experience comes from.

    Non-professional contexts must NEVER be converted into professional
    experience. A project using a technology supports "Used X in a project",
    never "N years of professional experience with X".
    """

    PROFESSIONAL = "professional"
    INTERNSHIP = "internship"
    FREELANCE = "freelance"
    ACADEMIC = "academic"
    PROJECT = "project"
    OPEN_SOURCE = "open_source"
    VOLUNTEERING = "volunteering"
    CERTIFICATION = "certification"
    TRAINING = "training"
    OTHER = "other"


class OpportunityType(str, Enum):
    """Universal opportunity shapes (derived, never role-branched)."""

    MISSING_SKILL = "missing_skill"
    BURIED_EXPERIENCE = "buried_experience"
    PROJECT_LEVERAGE = "project_leverage"
    REPOSITION_TRANSFERABLE = "reposition_transferable"
    CLARIFY_RELEVANCE = "clarify_relevance"
    TOOL_EXPOSURE = "tool_exposure"


class OpportunityStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    SKIPPED = "skipped"


class TailoringImprovementOpportunity(_EvidenceBase):
    """One high-value area where candidate input could improve the resume."""

    id: str = Field(default_factory=_gen_id)
    requirement_id: str = Field(description="Stable id of the JD requirement")
    normalized_requirement: str = Field(description="Stem-normalized requirement key")
    display_label: str = Field(description="Short candidate-facing label")
    importance: str = Field(default="medium", description="high|medium|low")
    potential_impact: float = Field(default=0.0, ge=0.0, description="Estimated ATS value")
    existing_support: Optional[str] = Field(
        default=None, description="Related resume excerpt, if any (internal)"
    )
    opportunity_type: OpportunityType = OpportunityType.MISSING_SKILL
    related_resume_content: List[str] = Field(default_factory=list)
    candidate_context_options: List[ExperienceContext] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: OpportunityStatus = OpportunityStatus.PENDING
    # Candidate-facing copy (friendly; never harsh). Kept on the model so the
    # API and frontend share one translation layer.
    friendly_title: str = ""
    friendly_prompt: str = ""
    friendly_helper: str = ""

    def to_candidate_card(self) -> Dict[str, Any]:
        """Candidate-safe view: no provenance jargon, no harsh language."""
        return {
            "id": self.id,
            "requirement_id": self.requirement_id,
            "display_label": self.display_label,
            "friendly_title": self.friendly_title,
            "friendly_prompt": self.friendly_prompt,
            "friendly_helper": self.friendly_helper,
            "context_options": [c.value for c in self.candidate_context_options],
            "confidence": self.confidence,
            "status": self.status.value,
        }


class CandidateConfirmedFact(_EvidenceBase):
    """One structured fact extracted from the candidate's batch answer."""

    id: str = Field(default_factory=_gen_id)
    opportunity_id: str
    requirement_id: str = ""
    normalized_requirement: str = ""
    display_label: str
    selected: bool = True
    candidate_context: ExperienceContext = ExperienceContext.OTHER
    # Candidate's own words (trimmed). Never augmented with invented detail.
    candidate_description: str = ""
    project_name: Optional[str] = None
    # Internal provenance marker: always candidate-confirmed, never inferred
    # as professional unless the candidate explicitly described employment.
    provenance: str = "candidate_confirmed"
    confidence: float = 0.7

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class CandidateExperienceResponse(_EvidenceBase):
    """The candidate's single collective answer to a batch of opportunities."""

    opportunity_ids: List[str] = Field(default_factory=list)
    selected_ids: List[str] = Field(default_factory=list)
    # One shared free-text input covering every selected opportunity.
    free_text: str = ""
    # Optional per-opportunity context hints chosen via UI chips.
    context_hints: Dict[str, ExperienceContext] = Field(default_factory=dict)

    def skipped(self) -> bool:
        return len(self.selected_ids) == 0


class ExtractedBatchResult(_EvidenceBase):
    """Outcome of parsing one natural-language batch answer."""

    facts: List[CandidateConfirmedFact] = Field(default_factory=list)
    declined_ids: List[str] = Field(default_factory=list)
    # At most one compact clarification covering all genuinely missing
    # details — never one follow-up per skill.
    needs_clarification: Optional[str] = None
    unusable_ids: List[str] = Field(default_factory=list)


class RetailorImpact(_EvidenceBase):
    """Before/after impact summary in honest, non-promising language."""

    baseline_score: float = 0.0
    tailored_score: float = 0.0
    delta: float = 0.0
    materially_improved: bool = False
    headline: str = ""
    improvements: List[str] = Field(default_factory=list)
    explanation: str = ""
