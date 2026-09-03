"""Resume Improvement Engine models.

Target 5.1 — Truthful Resume Improvement & Evidence Gathering.

Produces per-requirement improvement assessments that NEVER manufacture
experience. The engine distinguishes:
  - ALREADY_STRONG
  - PRESENT_BUT_WEAK
  - PRESENT_BUT_UNDERREPRESENTED
    - NO_EVIDENCE                (explain the gap; never invent)

Every classification and proposed wording is grounded in verified resume
evidence. This module only gathers intelligence — it never rewrites the resume.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class ImprovementClassification(str, Enum):
    """Actionable classification for an ATS requirement."""

    ALREADY_STRONG = "already_strong"
    PRESENT_BUT_WEAK = "present_but_weak"
    PRESENT_BUT_UNDERREPRESENTED = "present_but_underrepresented"
    NO_EVIDENCE = "no_evidence"


class EvidenceType(str, Enum):
    """Truthful evidence provenance — never conflated with employment."""

    PROFESSIONAL = "professional"
    INTERNSHIP = "internship"
    PROJECT = "project"
    ACADEMIC = "academic"
    CERTIFICATION = "certification"
    ACHIEVEMENT = "achievement"
    RESUME = "resume"


import uuid


class ImprovementProposal(BaseModel):
    """Actionable improvement proposal grounded in verified resume evidence."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique proposal identifier")
    requirement_id: str = Field(description="Associated requirement ID")
    target_section: Optional[str] = Field(default=None, description="Target section path, e.g. projects[0] or experience[1]")
    target_entry_id: Optional[str] = Field(default=None, description="Identifier of the specific target entry if available")
    provenance: Optional[str] = Field(default=None, description="Truthful evidence provenance (project, internship, professional, academic, etc.)")
    original_text: Optional[str] = Field(default=None, description="Original resume bullet or text being improved")
    proposed_wording: str = Field(description="AI-generated truthful wording grounded in evidence")
    rationale: Optional[str] = Field(default=None, description="Explanation of why this proposal improves ATS alignment without fabricating facts")
    diff_summary: Optional[str] = Field(default=None, description="Concise summary of changes made")
    metrics_prompt: Optional[str] = Field(default=None, description="Prompt asking for real metrics when none exist in evidence")
    evidence_sources: List[str] = Field(default_factory=list, description="Source excerpts grounding this proposal")
    safety_flags: List[str] = Field(default_factory=list, description="Safety or anti-hallucination flags raised")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    ai_generated: bool = Field(default=False, description="Whether LLM generated this proposal vs deterministic fallback")


class ImprovementAssessment(BaseModel):
    """Per-requirement improvement intelligence output."""

    requirement_id: str = Field(description="Stable requirement ID matching ATS requirement_coverage")
    classification: ImprovementClassification = Field(description="Actionable classification")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Engine confidence 0-1")
    existing_evidence: List[str] = Field(default_factory=list, description="Verified resume evidence excerpts")
    evidence_source: Optional[str] = Field(default=None, description="Section provenance path (e.g. experience[0])")
    evidence_type: Optional[EvidenceType] = Field(default=None, description="Truthful evidence provenance type")
    current_wording: Optional[str] = Field(default=None, description="Current resume wording being assessed")
    proposed_wording: Optional[str] = Field(
        default=None,
        description="AI-proposed wording using ONLY evidence; null when insufficient",
    )
    rationale: Optional[str] = Field(default=None, description="Why this classification/action")

    safety_flags: List[str] = Field(default_factory=list, description="Safety concerns detected")
    ai_generated: bool = Field(default=False, description="Produced by the LLM (vs deterministic fallback)")
    proposals: List[ImprovementProposal] = Field(default_factory=list, description="Grounded improvement proposals")
    requirements: Optional[Dict[str, Any]] = Field(default=None, description="Reserved for future use")


class ImprovementBatchResult(BaseModel):
    """Result of a batched improvement assessment run."""

    assessments: List[ImprovementAssessment] = Field(default_factory=list)
    success: bool = True
    fallback_used: bool = False
    message: str = ""
    provider_used: Optional[str] = None
    model_used: Optional[str] = None
    latency_ms: Optional[float] = None


class ProposalDecisionState(str, Enum):
    """Target 5.4 — Explicit user decision state for improvement proposals."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ProposalEligibility(str, Enum):
    """Target 5.4 — Deterministic eligibility classification for proposals."""

    ELIGIBLE = "eligible"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


from datetime import datetime


class ProposalDecision(BaseModel):
    """Target 5.4 — Audit record of user decision on an improvement proposal."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    resume_id: str
    report_id: str
    proposal_id: str
    requirement_id: str
    decision: ProposalDecisionState = Field(default=ProposalDecisionState.PENDING)
    eligibility: ProposalEligibility = Field(default=ProposalEligibility.ELIGIBLE)
    eligibility_reasons: List[str] = Field(default_factory=list)
    target_section: Optional[str] = None
    target_entry_id: Optional[str] = None
    original_text: Optional[str] = None
    proposed_wording: Optional[str] = None
    rationale: Optional[str] = None
    diff_summary: Optional[str] = None
    metrics_prompt: Optional[str] = None
    provenance: Optional[str] = None
    evidence_sources: List[str] = Field(default_factory=list, description="Source excerpts grounding this proposal")

    safety_flags: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    decided_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ApprovedProposal(BaseModel):
    """Target 5.4 — Single approved change ready for future editor ingestion."""

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
    evidence_sources: List[str] = Field(default_factory=list, description="Source excerpts grounding this proposal")

    safety_flags: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    approved_at: datetime = Field(default_factory=datetime.utcnow)


class ApprovedChangeSet(BaseModel):
    """Target 5.4 — Explicit approved change set domain object.

    Contains ONLY approved proposals. Does NOT perform any resume rewriting
    or document mutation (Target 5.5 boundary).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    resume_id: str
    report_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    proposals: List[ApprovedProposal] = Field(default_factory=list)
    total_approved: int = 0
    total_pending: int = 0
    total_rejected: int = 0
    status: str = "active"
