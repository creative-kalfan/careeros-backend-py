"""API schemas for AI Resume Optimization (Step 5)."""

from __future__ import annotations

from typing import Any, Optional, List, Dict, Literal
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum
import uuid


def _to_camel(snake_str: str) -> str:
    """Convert snake_case to camelCase."""
    components = snake_str.split("_")
    return components[0] + "".join(p.title() for p in components[1:])


class OptimizationType(str, Enum):
    """Types of optimization suggestions."""
    PROFESSIONAL_SUMMARY = "professional_summary"
    EXPERIENCE_BULLET = "experience_bullet"
    PROJECT_BULLET = "project_bullet"
    SKILLS_ALIGNMENT = "skills_alignment"
    KEYWORD_PLACEMENT = "keyword_placement"
    SECTION_PRIORITIZATION = "section_prioritization"


class SuggestionCategory(str, Enum):
    ALREADY_PRESENT = "already_present"
    MISSING_WITHOUT_EVIDENCE = "missing_without_evidence"
    POSSIBLY_PRESENT = "possibly_present"


class SuggestionAction(str, Enum):
    KEEP = "keep"
    DO_NOT_ADD = "do_not_add"
    VERIFY = "verify"


class SuggestionStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED = "edited"


class SuggestionPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class OptimizationSuggestionSchema(BaseModel):
    """Optimization suggestion schema for API responses."""
    id: str
    type: str
    priority: str
    section: Optional[str] = None
    entry_id: Optional[str] = None
    child_id: Optional[str] = None
    current_text: Optional[str] = None
    suggested_text: Optional[str] = None
    explanation: str
    evidence: List[str] = []
    affected_keywords: List[str] = []
    category: Optional[str] = None
    action: Optional[str] = None
    skill: Optional[str] = None
    similar_in_resume: Optional[str] = None
    status: str = "pending"
    evidence_issues: List[str] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OptimizationSessionSchema(BaseModel):
    """Optimization session schema for API responses."""
    id: str
    resume_id: str
    version_id: Optional[str] = None
    ats_report_id: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    job_description: str
    created_at: datetime
    updated_at: datetime
    status: str = "active"
    suggestions_generated: int = 0
    suggestions_accepted: int = 0
    suggestions_rejected: int = 0
    current_ats_score: Optional[float] = None
    baseline_ats_score: Optional[float] = None
    target_job_title: Optional[str] = None
    target_company: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class OptimizationSuggestionRecordSchema(BaseModel):
    """Optimization suggestion record for API responses."""
    id: str
    session_id: str
    suggestion: OptimizationSuggestionSchema
    resume_snapshot: Optional[Dict[str, Any]] = None
    applied: bool = False
    applied_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OptimizeResumeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    resume_id: str
    version_id: Optional[str] = None
    job_description: str
    job_title: Optional[str] = None
    company: Optional[str] = None
    ats_report_id: Optional[str] = None


class OptimizeResumeResponse(BaseModel):
    session_id: str
    suggestions: List[Dict[str, Any]]
    message: str
    evidence_issues: List[str] = []


class AcceptSuggestionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    session_id: str
    suggestion_id: str
    edited_text: Optional[str] = None


class RejectSuggestionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    session_id: str
    suggestion_id: str
    reason: Optional[str] = None


class SuggestionActionResponse(BaseModel):
    success: bool
    suggestion_id: str
    status: str
    updated_resume: Optional[Dict[str, Any]] = None
    message: str


class OptimizationSessionResponse(BaseModel):
    session: Dict[str, Any]
    suggestions: List[Dict[str, Any]]


class ListOptimizationSessionsResponse(BaseModel):
    sessions: List[Dict[str, Any]]


class ReanalyzeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    resume_id: str
    session_id: str
    job_description: str
    job_title: Optional[str] = None
    company: Optional[str] = None


class ReanalyzeResponse(BaseModel):
    previous_score: float
    current_score: float
    delta: float
    report_id: str
    message: str


class GenerateSkillsOptimizationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    resume_id: str
    version_id: Optional[str] = None
    job_description: str
    job_title: Optional[str] = None
    company: Optional[str] = None


class GenerateSkillsOptimizationResponse(BaseModel):
    session_id: str
    suggestions: List[Dict[str, Any]]
    message: str
    evidence_issues: List[str] = []


class GenerateSummaryOptimizationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    resume_id: str
    version_id: Optional[str] = None
    job_description: str
    job_title: Optional[str] = None
    company: Optional[str] = None


class GenerateSummaryOptimizationResponse(BaseModel):
    session_id: str
    suggestions: List[Dict[str, Any]]
    message: str
    evidence_issues: List[str] = []


class GenerateExperienceBulletOptimizationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    resume_id: str
    version_id: Optional[str] = None
    job_description: str
    job_title: Optional[str] = None
    company: Optional[str] = None
    entry_id: str
    bullet_id: str
    bullet_text: str


class GenerateExperienceBulletOptimizationResponse(BaseModel):
    session_id: str
    suggestions: List[Dict[str, Any]]
    message: str
    evidence_issues: List[str] = []


class OptimizationHistoryItemSchema(BaseModel):
    session_id: str
    job_title: Optional[str]
    company: Optional[str]
    baseline_score: Optional[float]
    final_score: Optional[float]
    suggestions_count: int
    accepted_count: int
    created_at: datetime
    status: str

    model_config = ConfigDict(from_attributes=True)


class ListOptimizationHistoryResponse(BaseModel):
    history: List[OptimizationHistoryItemSchema]


class GetSessionSuggestionsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    session_id: str


class GetSessionSuggestionsResponse(BaseModel):
    suggestions: List[Dict[str, Any]]
    session: Dict[str, Any]


class ApplySuggestionsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    session_id: str
    suggestion_ids: List[str]


class ApplySuggestionsResponse(BaseModel):
    success: bool
    updated_resume: Dict[str, Any]
    applied_count: int
    message: str


class CreateJobSpecificResumeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    session_id: str
    name: str


class CreateJobSpecificResumeResponse(BaseModel):
    success: bool
    resume_id: str
    message: str


class ReanalyzeResponseSchema(BaseModel):
    previous_score: float
    current_score: float
    delta: float
    report_id: str
    message: str