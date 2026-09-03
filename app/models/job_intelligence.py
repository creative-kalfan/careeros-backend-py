"""Job Intelligence models for CareerOS."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class SeniorityInfo(BaseModel):
    """Seniority information extracted from a job description."""
    level: Optional[str] = None
    years_min: Optional[float] = None
    years_max: Optional[float] = None
    confidence: str = "low"


class WorkArrangement(BaseModel):
    """Work arrangement classification."""
    type: str = "unknown"  # onsite, hybrid, remote, unknown
    confidence: str = "low"


class SkillInfo(BaseModel):
    """Extracted skill with metadata."""
    name: str
    normalized_name: str
    category: Optional[str] = None
    importance: str = "mentioned"  # required, preferred, mentioned
    evidence: str = ""
    confidence: str = "low"


class RequirementInfo(BaseModel):
    """Extracted job requirement."""
    text: str
    type: str = "keyword"  # required, preferred, responsibility, qualification, skill, keyword
    importance: str = "medium"  # high, medium, low
    confidence: str = "low"


class EducationInfo(BaseModel):
    """Extracted education requirement."""
    degree: Optional[str] = None
    field: Optional[str] = None
    required: bool = False
    confidence: str = "low"


class CertificationInfo(BaseModel):
    """Extracted certification requirement."""
    name: str
    required: bool = False
    confidence: str = "low"


class JobIntelligence(BaseModel):
    """Structured intelligence extracted from a job description.

    This is a separate representation from NormalizedJob. It captures
    structured insights derived from the job description text, not the
    raw job data itself.
    """
    job_id: str
    intelligence_version: str = "1.0"
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    seniority: SeniorityInfo = Field(default_factory=SeniorityInfo)
    skills: list[SkillInfo] = Field(default_factory=list)
    requirements: list[RequirementInfo] = Field(default_factory=list)
    education: list[EducationInfo] = Field(default_factory=list)
    certifications: list[CertificationInfo] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    work_arrangement: WorkArrangement = Field(default_factory=WorkArrangement)

    def to_db_row(self) -> dict[str, Any]:
        """Convert to a database row for the job_intelligence table."""
        return {
            "job_id": self.job_id,
            "intelligence_version": self.intelligence_version,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "seniority": self.seniority.model_dump(),
            "skills": [s.model_dump() for s in self.skills],
            "requirements": [r.model_dump() for r in self.requirements],
            "education": [e.model_dump() for e in self.education],
            "certifications": [c.model_dump() for c in self.certifications],
            "keywords": self.keywords,
            "responsibilities": self.responsibilities,
            "industries": self.industries,
            "work_arrangement": self.work_arrangement.model_dump(),
        }
