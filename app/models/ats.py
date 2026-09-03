"""ATS Intelligence models for CareerOS Resume Module (Step 4)."""

from __future__ import annotations

from typing import Any, Optional, List, Dict
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum

class JobRequirementType(str, Enum):
    """Types of job requirements."""
    REQUIRED = "required"
    PREFERRED = "preferred"
    RESPONSIBILITY = "responsibility"
    SKILL = "skill"
    QUALIFICATION = "qualification"
    KEYWORD = "keyword"
    EXPERIENCE = "experience"
    WORK_CONDITION = "work_condition"

class ParsedJobRequirement(BaseModel):
    """Structured representation of a parsed job requirement."""
    text: str
    requirement_type: JobRequirementType
    confidence: float = 1.0  # 0.0 to 1.0 confidence in classification
    source_section: Optional[str] = None  # e.g., "Requirements", "Skills"

class ParsedJobDescription(BaseModel):
    """Structured representation of a parsed job description."""
    raw_text: str
    job_title: Optional[str] = None
    company: Optional[str] = None
    required_skills: List[str] = []
    preferred_skills: List[str] = []
    technical_skills: List[str] = []
    soft_skills: List[str] = []
    years_of_experience: Optional[str] = None
    education_requirements: List[str] = []
    certifications: List[str] = []
    responsibilities: List[str] = []
    qualifications: List[str] = []
    keywords: List[str] = []
    tools_technologies: List[str] = []
    domain_terms: List[str] = []
    parsed_requirements: List[ParsedJobRequirement] = []
    extracted_at: datetime = Field(default_factory=datetime.now)

class EvidenceLevel(str, Enum):
    """Level of evidence for requirement coverage."""
    STRONG = "strong"
    PARTIAL = "partial"
    NONE = "none"

class RequirementCoverage(BaseModel):
    """Coverage analysis for a specific job requirement."""
    requirement: str
    requirement_type: JobRequirementType
    resume_evidence: List[str] = []
    evidence_level: EvidenceLevel = EvidenceLevel.NONE
    evidence_sources: List[str] = []  # e.g., ["skills", "experience"]

    # Enriched, concept-level fields (V2 requirement intelligence).
    category: Optional[str] = None  # requirement|skill|qualification|experience|work_condition|responsibility
    importance: Optional[str] = None  # high|medium|low
    status: Optional[str] = None  # matched|partial|missing
    job_evidence: Optional[str] = None  # the JD variant that triggered this requirement

    # LLM semantic reasoning fields
    semantic_status: Optional[SemanticMatchStatus] = None
    semantic_confidence: Optional[float] = None
    semantic_evidence: Optional[str] = None
    semantic_reasoning: Optional[str] = None
    semantic_evidence_strength: Optional[SemanticEvidenceStrength] = None
    reasoning_source: Optional[str] = None  # Deterministic|LLM|DeterministicOverride

    # Target 4.1: Requirement → Resume Evidence Mapping
    deterministic_status: Optional[str] = None  # original deterministic status before reconciliation
    evidence_source_section: Optional[str] = None  # which resume section provided evidence (e.g., "skills", "experience[0]", "projects[1]")
    evidence_explanation: Optional[str] = None  # user-safe explanation of the evidence mapping

class ATSAnalysisResult(BaseModel):
    """Comprehensive ATS analysis result."""
    overall_score: float = Field(..., ge=0, le=100)
    keyword_match_score: float = Field(..., ge=0, le=100)
    skills_match_score: float = Field(..., ge=0, le=100)
    experience_relevance_score: float = Field(..., ge=0, le=100)
    qualification_match_score: float = Field(..., ge=0, le=100)
    structure_format_score: float = Field(..., ge=0, le=100)

    matched_keywords: List[str] = []
    missing_keywords: List[str] = []
    partial_keywords: List[str] = []

    matched_skills: List[str] = []
    missing_skills: List[str] = []
    partial_skills: List[str] = []

    requirement_coverage: List[RequirementCoverage] = []

    recommendations: List[str] = []
    high_priority_recommendations: List[str] = []
    medium_priority_recommendations: List[str] = []
    low_priority_recommendations: List[str] = []

    template_analysis: Dict[str, Any] = {}
    section_analysis: Dict[str, Any] = {}

    analysis_explanation: Dict[str, str] = {}
    scoring_version: str = "1.0"

    # LLM semantic reasoning metadata
    semantic_metadata: Optional[ATSAnalysisMetadata] = None

class ATSAnalysisReport(BaseModel):
    """Persistent ATS analysis report stored in database."""
    id: str
    resume_id: str
    version_id: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    job_description: str
    parsed_job_data: Dict[str, Any]
    overall_score: float
    keyword_match_score: float
    skills_match_score: float
    experience_relevance_score: float
    qualification_match_score: float
    structure_format_score: float
    matched_keywords: List[str]
    missing_keywords: List[str]
    partial_keywords: List[str]
    matched_skills: List[str]
    missing_skills: List[str]
    partial_skills: List[str]
    requirement_analysis: List[Dict[str, Any]]
    recommendations: List[str]
    high_priority_recommendations: List[str]
    medium_priority_recommendations: List[str]
    low_priority_recommendations: List[str]
    template_analysis: Dict[str, Any]
    section_analysis: Dict[str, Any]
    analysis_explanation: Dict[str, str]
    scoring_version: str
    created_at: datetime
    updated_at: datetime

class ATSScoringConfig(BaseModel):
    """Configurable scoring weights for ATS analysis."""
    keyword_weight: float = 0.25
    skills_weight: float = 0.25
    experience_weight: float = 0.20
    qualification_weight: float = 0.15
    structure_weight: float = 0.15

    # Section importance weights
    experience_importance: float = 0.4
    skills_importance: float = 0.3
    education_importance: float = 0.2
    projects_importance: float = 0.1

    # Fresher vs experienced candidate adjustments
    fresher_experience_weight: float = 0.2
    experienced_experience_weight: float = 0.4

class SkillNormalizationEntry(BaseModel):
    """Skill normalization mapping entry."""
    canonical_name: str
    variants: List[str] = []
    category: Optional[str] = None

class SkillNormalizationDictionary(BaseModel):
    """Skill normalization dictionary."""
    entries: List[SkillNormalizationEntry] = []
    version: str = "1.0"


# ---------------------------------------------------------------------------
# LLM-Powered Semantic Reasoning Models
# ---------------------------------------------------------------------------

class SemanticMatchStatus(str, Enum):
    """Semantic match status for a requirement against resume evidence."""
    MATCHED = "matched"
    PARTIAL = "partial"
    MISSING = "missing"
    UNKNOWN = "unknown"


class SemanticEvidenceStrength(str, Enum):
    """Strength of semantic evidence from the LLM."""
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    NONE = "none"


class SemanticRequirementAssessment(BaseModel):
    """LLM-generated semantic assessment for a single requirement."""
    requirement_id: str = Field(description="Unique ID matching the deterministic concept canonical name")
    status: SemanticMatchStatus = Field(description="Semantic match classification")
    confidence: float = Field(ge=0.0, le=1.0, description="How strongly the evidence supports this classification")
    evidence: Optional[str] = Field(default=None, description="Exact resume excerpt used as evidence")
    reasoning: str = Field(description="Short user-safe explanation of the semantic relationship")
    evidence_strength: SemanticEvidenceStrength = Field(description="Strength of the evidence linking requirement to resume")


class SemanticAnalysisResult(BaseModel):
    """Complete LLM semantic analysis output for all requirements."""
    assessments: List[SemanticRequirementAssessment] = Field(default_factory=list)
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    latency_ms: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None
    overall_score_rejection: Optional[float] = Field(
        default=None,
        description="If the LLM returned an overall_score, it is captured here but IGNORED"
    )


class ReconciledRequirement(BaseModel):
    """Final reconciled status for a requirement after deterministic + semantic merge."""
    requirement: str
    requirement_type: JobRequirementType
    category: Optional[str] = None
    importance: Optional[str] = None

    deterministic_status: Optional[str] = None
    deterministic_evidence: Optional[str] = None

    semantic_status: Optional[SemanticMatchStatus] = None
    semantic_confidence: Optional[float] = None
    semantic_evidence: Optional[str] = None
    semantic_reasoning: Optional[str] = None
    semantic_evidence_strength: Optional[SemanticEvidenceStrength] = None

    final_status: str = Field(description="Reconciled final status: matched|partial|missing")
    final_evidence: Optional[str] = None
    reasoning_source: str = Field(description="Deterministic|LLM|DeterministicOverride")


class ATSAnalysisMetadata(BaseModel):
    """Metadata about the semantic reasoning layer for the ATS result."""
    semantic_available: bool = Field(default=False, description="Whether semantic reasoning was attempted")
    semantic_success: bool = Field(default=False, description="Whether semantic analysis completed successfully")
    semantic_model: Optional[str] = None
    semantic_provider: Optional[str] = None
    semantic_latency_ms: Optional[float] = None
    reconciled_count: int = Field(default=0, description="Number of requirements reconciled")
    semantic_upgrades: int = Field(default=0, description="Count of requirements upgraded from MISSING by semantic evidence")
    semantic_overrides: int = Field(default=0, description="Count of LLM assessments overridden by validation")