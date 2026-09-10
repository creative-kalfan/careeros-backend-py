"""API schemas for friendly batch evidence discovery (tailoring)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(snake_str: str) -> str:
    components = snake_str.split("_")
    return components[0] + "".join(p.title() for p in components[1:])


class _CamelBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)


class OpportunityRequest(_CamelBase):
    resume_id: Optional[str] = None
    version_id: Optional[str] = None
    job_description: str
    job_title: Optional[str] = None
    company: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    max_opportunities: Optional[int] = None
    known_fact_keys: List[str] = Field(default_factory=list)
    declined_requirement_ids: List[str] = Field(default_factory=list)


class OpportunityCardSchema(_CamelBase):
    id: str
    requirement_id: str
    display_label: str
    friendly_title: str
    friendly_prompt: str
    friendly_helper: str
    context_options: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    status: str = "pending"


class OpportunityResponse(_CamelBase):
    success: bool = True
    heading: str = ""
    subheading: str = ""
    select_hint: str = ""
    input_label: str = ""
    input_placeholder: str = ""
    skip_label: str = ""
    submit_label: str = ""
    opportunities: List[OpportunityCardSchema] = Field(default_factory=list)
    message: str = ""


class ConfirmedFactSchema(_CamelBase):
    id: str
    opportunity_id: str
    requirement_id: str = ""
    display_label: str = ""
    candidate_context: str = "other"
    candidate_description: str = ""
    project_name: Optional[str] = None
    provenance: str = "candidate_confirmed"
    confidence: float = 0.0


class RespondRequest(_CamelBase):
    resume_id: Optional[str] = None
    version_id: Optional[str] = None
    job_description: str
    job_title: Optional[str] = None
    company: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    opportunities: List[Dict[str, Any]] = Field(default_factory=list)
    selected_ids: List[str] = Field(default_factory=list)
    free_text: str = ""
    context_hints: Dict[str, str] = Field(default_factory=dict)


class PlanItemSchema(_CamelBase):
    section: str
    action: str = "ALIGN"
    target_id: Optional[str] = None
    current_text: Optional[str] = None
    suggested_text: Optional[str] = None
    reasoning: str = ""
    keywords_addressed: List[str] = Field(default_factory=list)


class ImpactSchema(_CamelBase):
    baseline_score: float = 0.0
    tailored_score: float = 0.0
    delta: float = 0.0
    materially_improved: bool = False
    headline: str = ""
    improvements: List[str] = Field(default_factory=list)
    explanation: str = ""


class RespondResponse(_CamelBase):
    success: bool = True
    facts: List[ConfirmedFactSchema] = Field(default_factory=list)
    declined_ids: List[str] = Field(default_factory=list)
    needs_clarification: Optional[str] = None
    success_note: str = ""
    tailored_profile: Dict[str, Any] = Field(default_factory=dict)
    plan: List[PlanItemSchema] = Field(default_factory=list)
    impact: ImpactSchema = Field(default_factory=ImpactSchema)
    guard_issues: List[str] = Field(default_factory=list)
    message: str = ""
