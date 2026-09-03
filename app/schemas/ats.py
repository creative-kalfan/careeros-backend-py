"""ATS Intelligence API schemas for CareerOS Resume Module (Step 4)."""

from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

from app.models.ats import ATSAnalysisResult


def _to_camel(snake_str: str) -> str:
    """Convert snake_case to camelCase."""
    components = snake_str.split("_")
    return components[0] + "".join(p.title() for p in components[1:])

class AnalyzeResumeRequest(BaseModel):
    """Request schema for analyzing a resume against a job description."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    resume_id: str = Field(..., description="ID of the resume to analyze")
    version_id: Optional[str] = Field(None, description="Optional version ID for version-specific analysis")
    job_description: str = Field(..., description="Job description text")
    job_title: Optional[str] = Field(None, description="Optional job title")
    company: Optional[str] = Field(None, description="Optional company name")
    persist: bool = Field(True, description="Whether to persist the analysis result")

class AnalyzeResumeResponse(BaseModel):
    """Response schema for resume analysis."""
    result: ATSAnalysisResult
    report_id: Optional[str] = None
    message: str = "Analysis completed successfully"

class ATSAnalysisReportResponse(BaseModel):
    """Response schema for retrieving ATS analysis reports."""
    id: str
    resume_id: str
    version_id: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    overall_score: float
    keyword_match_score: float
    skills_match_score: float
    experience_relevance_score: float
    qualification_match_score: float
    structure_format_score: float
    created_at: datetime
    updated_at: datetime

class ListATSReportsResponse(BaseModel):
    """Response schema for listing ATS analysis reports."""
    reports: List[ATSAnalysisReportResponse]

class ATSAnalysisErrorResponse(BaseModel):
    """Error response schema for ATS analysis."""
    success: bool = False
    error: str
    details: Optional[dict] = None

class JobDescriptionParseRequest(BaseModel):
    """Request schema for parsing job descriptions."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)

    job_description: str = Field(..., description="Job description text")
    job_title: Optional[str] = Field(None, description="Optional job title")
    company: Optional[str] = Field(None, description="Optional company name")

class JobDescriptionParseResponse(BaseModel):
    """Response schema for parsed job descriptions."""
    parsed_job: dict
    extracted_keywords: List[str]
    extracted_skills: List[str]
    extracted_requirements: List[dict]