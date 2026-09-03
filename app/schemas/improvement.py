"""API schemas for Resume Improvement (Target 5.1)."""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


def _to_camel(snake_str: str) -> str:
    components = snake_str.split("_")
    return components[0] + "".join(p.title() for p in components[1:])


class ImprovementRequirementInput(BaseModel):
    """A single requirement coverage entry from the current ATS analysis.

    Mirrors RequirementCoverage so the endpoint consumes the SAME requirement
    IDs and evidence the frontend already holds — preserving stable IDs without
    re-running ATS analysis.
    """

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    requirement: str = Field(..., description="Requirement ID (stable)")
    category: Optional[str] = None
    importance: Optional[str] = None
    status: Optional[str] = None
    job_evidence: Optional[str] = None
    resume_evidence: List[str] = Field(default_factory=list)
    semantic_evidence: Optional[str] = None
    evidence_level: Optional[str] = None
    evidence_source_section: Optional[str] = None
    evidence_explanation: Optional[str] = None


class AssessImprovementRequest(BaseModel):
    """Request for batched improvement assessment."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    resume_id: str = Field(..., description="Resume ID")
    version_id: Optional[str] = Field(None, description="Optional version ID for version-specific assessment")
    job_title: Optional[str] = None
    company: Optional[str] = None
    category: Optional[str] = None
    requirements: List[ImprovementRequirementInput] = Field(
        default_factory=list, description="Requirement coverage from the current ATS analysis"
    )


class ImprovementProposalResponse(BaseModel):
    """API schema for an improvement proposal."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    id: str
    requirement_id: str
    target_section: Optional[str] = None
    target_entry_id: Optional[str] = None
    provenance: Optional[str] = None
    original_text: Optional[str] = None
    proposed_wording: str
    rationale: Optional[str] = None
    diff_summary: Optional[str] = None
    metrics_prompt: Optional[str] = None
    evidence_sources: List[str] = Field(default_factory=list)
    safety_flags: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    ai_generated: bool = False
    # Target 5.4 Review/Decision state fields
    decision: str = "pending"
    eligibility: str = "eligible"
    eligibility_reasons: List[str] = Field(default_factory=list)
    decided_at: Optional[str] = None


class ImprovementAssessmentResponse(BaseModel):
    """Per-requirement improvement assessment for the API response.

    Target 5.3: carries grounded improvement proposals for review.
    """

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    requirement_id: str
    classification: str
    confidence: float
    existing_evidence: List[str] = Field(default_factory=list)
    evidence_source: Optional[str] = None
    evidence_type: Optional[str] = None
    current_wording: Optional[str] = None
    proposed_wording: Optional[str] = None
    rationale: Optional[str] = None
    safety_flags: List[str] = Field(default_factory=list)
    ai_generated: bool = False
    proposals: List[ImprovementProposalResponse] = Field(default_factory=list)


class AssessImprovementResponse(BaseModel):
    """Response for a batched improvement assessment."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    success: bool = True
    fallback_used: bool = False
    message: str = ""
    provider_used: Optional[str] = None
    model_used: Optional[str] = None
    assessments: List[ImprovementAssessmentResponse] = Field(default_factory=list)


class ProposalDecisionRequest(BaseModel):
    """Target 5.4 — Request to set decision on an improvement proposal."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    decision: str = Field(..., description="Decision: pending, approved, or rejected")
    proposal: Optional[ImprovementProposalResponse] = Field(
        None, description="Full proposal metadata if available"
    )


class BulkDecisionRequest(BaseModel):
    """Target 5.4 — Request for bulk proposal decisions."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    action: str = Field(..., description="Action: approve_all_safe or reject_all")
    proposals: List[ImprovementProposalResponse] = Field(
        default_factory=list, description="Proposals to apply bulk action on"
    )


class ProposalDecisionResponse(BaseModel):
    """Target 5.4 — API response for a single proposal decision."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    id: str
    resume_id: str
    report_id: str
    proposal_id: str
    requirement_id: str
    decision: str
    eligibility: str
    eligibility_reasons: List[str] = Field(default_factory=list)
    target_section: Optional[str] = None
    target_entry_id: Optional[str] = None
    original_text: Optional[str] = None
    proposed_wording: Optional[str] = None
    rationale: Optional[str] = None
    diff_summary: Optional[str] = None
    metrics_prompt: Optional[str] = None
    provenance: Optional[str] = None
    evidence_sources: List[str] = Field(default_factory=list)
    safety_flags: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    decided_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ListProposalDecisionsResponse(BaseModel):
    """Target 5.4 — API response listing all proposal decisions for a report."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    success: bool = True
    decisions: List[ProposalDecisionResponse] = Field(default_factory=list)
    summary: Dict[str, int] = Field(default_factory=dict)


class ApprovedProposalResponse(BaseModel):
    """Target 5.4 — Single approved proposal in the change set."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    proposal_id: str
    requirement_id: str
    target_section: Optional[str] = None
    target_entry_id: Optional[str] = None
    original_text: Optional[str] = None
    proposed_wording: str
    rationale: Optional[str] = None
    diff_summary: Optional[str] = None
    metrics_prompt: Optional[str] = None
    provenance: Optional[str] = None
    evidence_sources: List[str] = Field(default_factory=list)
    safety_flags: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    approved_at: Optional[str] = None


class ApprovedChangeSetResponse(BaseModel):
    """Target 5.4 — Approved change set response."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    id: str
    resume_id: str
    report_id: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    proposals: List[ApprovedProposalResponse] = Field(default_factory=list)
    total_approved: int = 0
    total_pending: int = 0
    total_rejected: int = 0
    status: str = "active"


class BulkDecisionResponse(BaseModel):
    """Target 5.4 — API response for bulk decision execution."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    success: bool = True
    action: str
    updated_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    skipped_blocked_count: int = 0
    decisions: List[ProposalDecisionResponse] = Field(default_factory=list)


class ApplyApprovedImprovementsRequest(BaseModel):
    """Target 5.5 — Request to apply approved improvements to structured resume."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    version_id: Optional[str] = Field(None, description="Target version ID to update; if none, uses master/latest")
    proposal_ids: Optional[List[str]] = Field(None, description="Specific approved proposal IDs to apply; if none, applies all approved")
    create_derived_version: bool = Field(True, description="Create a new immutable derived version to preserve original")
    version_name: Optional[str] = Field(None, description="Optional custom name for newly created version")


class AppliedProposalSummaryResponse(BaseModel):
    """Target 5.5 — Summary of a successfully applied proposal mutation."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    proposal_id: str
    requirement_id: str
    target_section: Optional[str] = None
    original_text: Optional[str] = None
    applied_text: str
    provenance: Optional[str] = None
    summary: Optional[str] = None
    status: str = "applied"


class ApplyApprovedImprovementsResponse(BaseModel):
    """Target 5.5 — API response for applying approved improvements."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    success: bool = True
    resume_id: str
    report_id: str
    version_id: str
    version_name: str
    is_new_version: bool = True
    applied_count: int = 0
    applied_proposals: List[AppliedProposalSummaryResponse] = Field(default_factory=list)
    message: str = ""


