"""AI Resume Optimization models for CareerOS Resume Module (Step 5)."""

from __future__ import annotations

from typing import Any, Optional, List, Dict, Literal
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum
import uuid


class OptimizationType(str, Enum):
    """Types of optimization suggestions."""
    PROFESSIONAL_SUMMARY = "professional_summary"
    EXPERIENCE_BULLET = "experience_bullet"
    PROJECT_BULLET = "project_bullet"
    SKILLS_ALIGNMENT = "skills_alignment"
    KEYWORD_PLACEMENT = "keyword_placement"
    SECTION_PRIORITIZATION = "section_prioritization"


class SuggestionCategory(str, Enum):
    """Categories for skill alignment suggestions."""
    ALREADY_PRESENT = "already_present"
    MISSING_WITHOUT_EVIDENCE = "missing_without_evidence"
    POSSIBLY_PRESENT = "possibly_present"


class SuggestionAction(str, Enum):
    """Actions for skill alignment suggestions."""
    KEEP = "keep"
    DO_NOT_ADD = "do_not_add"
    VERIFY = "verify"


class SuggestionStatus(str, Enum):
    """Status of an optimization suggestion."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED = "edited"


class SuggestionPriority(str, Enum):
    """Priority level of a suggestion."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class OptimizationSuggestion(BaseModel):
    """Structured optimization suggestion."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: OptimizationType
    priority: SuggestionPriority = SuggestionPriority.MEDIUM
    section: Optional[str] = None  # e.g., "experience", "projects", "summary"
    entry_id: Optional[str] = None  # ID of the specific entry (experience/project)
    current_text: Optional[str] = None
    suggested_text: Optional[str] = None
    explanation: str
    evidence: List[str] = []
    affected_keywords: List[str] = []
    category: Optional[SuggestionCategory] = None
    action: Optional[SuggestionAction] = None
    skill: Optional[str] = None
    similar_in_resume: Optional[str] = None
    status: SuggestionStatus = SuggestionStatus.PENDING
    evidence_issues: List[str] = []
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class OptimizationSession(BaseModel):
    """Optimization session tracking."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    resume_id: str
    ats_report_id: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    job_description: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    status: Literal["active", "completed", "abandoned"] = "active"
    suggestions_generated: int = 0
    suggestions_accepted: int = 0
    suggestions_rejected: int = 0
    current_ats_score: Optional[float] = None
    baseline_ats_score: Optional[float] = None
    target_job_title: Optional[str] = None
    target_company: Optional[str] = None


class OptimizationSuggestionRecord(BaseModel):
    """Persistent optimization suggestion record stored in database."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    suggestion: OptimizationSuggestion
    resume_snapshot: Optional[Dict[str, Any]] = None  # Resume content at time of suggestion
    applied: bool = False
    applied_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class OptimizeResumeRequest(BaseModel):
    """Request to generate optimization suggestions."""
    resume_id: str
    job_description: str
    job_title: Optional[str] = None
    company: Optional[str] = None
    ats_report_id: Optional[str] = None


class OptimizationSuggestionResponse(BaseModel):
    """Response with generated optimization suggestions."""
    session_id: str
    suggestions: List[OptimizationSuggestion]
    message: str
    evidence_issues: List[str] = []


class AcceptSuggestionRequest(BaseModel):
    """Request to accept a suggestion."""
    session_id: str
    suggestion_id: str
    edited_text: Optional[str] = None  # If user edited before accepting


class RejectSuggestionRequest(BaseModel):
    """Request to reject a suggestion."""
    session_id: str
    suggestion_id: str
    reason: Optional[str] = None


class SuggestionActionResponse(BaseModel):
    """Response after accepting/rejecting a suggestion."""
    success: bool
    suggestion_id: str
    status: SuggestionStatus
    updated_resume: Optional[Dict[str, Any]] = None
    message: str


class OptimizationSessionResponse(BaseModel):
    """Response with optimization session details."""
    session: OptimizationSession
    suggestions: List[OptimizationSuggestionRecord]


class ListOptimizationSessionsResponse(BaseModel):
    """Response with list of optimization sessions."""
    sessions: List[OptimizationSession]


class ReanalyzeRequest(BaseModel):
    """Request to re-analyze after applying suggestions."""
    resume_id: str
    session_id: str
    job_description: str
    job_title: Optional[str] = None
    company: Optional[str] = None


class ReanalyzeResponse(BaseModel):
    """Response after re-analysis."""
    previous_score: float
    current_score: float
    delta: float
    report_id: str
    message: str


class OptimizationHistoryItem(BaseModel):
    """Optimization history item for display."""
    session_id: str
    job_title: Optional[str]
    company: Optional[str]
    baseline_score: Optional[float]
    final_score: Optional[float]
    suggestions_count: int
    accepted_count: int
    created_at: datetime
    status: str


class ListOptimizationHistoryResponse(BaseModel):
    """Response with optimization history."""
    history: List[OptimizationHistoryItem]


# Request/Response for getting suggestions for a session
class GetSessionSuggestionsRequest(BaseModel):
    session_id: str


class GetSessionSuggestionsResponse(BaseModel):
    suggestions: List[OptimizationSuggestionRecord]
    session: OptimizationSession


# Request/Response for applying suggestions and getting updated resume
class ApplySuggestionsRequest(BaseModel):
    session_id: str
    suggestion_ids: List[str]


class ApplySuggestionsResponse(BaseModel):
    success: bool
    updated_resume: Dict[str, Any]
    applied_count: int
    message: str


class CreateJobSpecificResumeRequest(BaseModel):
    """Request to create a job-specific resume version."""
    session_id: str
    name: str  # e.g., "Data Analyst — Barclays"


class CreateJobSpecificResumeResponse(BaseModel):
    success: bool
    resume_id: str
    message: str