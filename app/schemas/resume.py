"""Resume API schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.resume import ResumeContent, ResumeMeta, ResumeProfile


class ResumeRecordResponse(BaseModel):
    id: str
    user_id: str
    title: str
    file_url: Optional[str] = None
    original_filename: Optional[str] = None
    storage_path: Optional[str] = None
    parse_status: str
    content: Optional[dict[str, Any]] = None
    meta: Optional[dict[str, Any]] = None
    created_at: str
    updated_at: str


class ResumeVersionResponse(BaseModel):
    id: str
    resume_id: str
    version_name: str
    source: str
    content: dict[str, Any]
    target_job_title: str | None = None
    target_company: str | None = None
    target_job_id: str | None = None
    target_job_url: str | None = None
    job_description: str | None = None
    template: str = "minimal"
    status: str = "active"
    is_master: bool = False
    parent_version_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    last_ats_score: float | None = None
    last_analyzed_at: str | None = None
    sections_config: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ResumeVersionCreate(BaseModel):
    version_name: str = "Untitled Version"
    parent_version_id: str | None = None
    target_job_title: str | None = None
    target_company: str | None = None
    target_job_id: str | None = None
    target_job_url: str | None = None
    job_description: str | None = None
    template: str = "minimal"
    source: str = "manual"
    content: dict[str, Any] = Field(default_factory=dict)
    sections_config: dict[str, Any] = Field(default_factory=dict)


class ResumeVersionUpdate(BaseModel):
    version_name: str | None = None
    target_job_title: str | None = None
    target_company: str | None = None
    target_job_id: str | None = None
    target_job_url: str | None = None
    job_description: str | None = None
    template: str | None = None
    status: str | None = None
    content: dict[str, Any] | None = None
    sections_config: dict[str, Any] | None = None
    last_ats_score: float | None = None
    last_analyzed_at: str | None = None


class ApplyVersionOperationRequest(BaseModel):
    operation: str = Field(..., pattern="^(replace|insert|delete)$")
    section: str
    target_id: str | None = None
    replacement: dict[str, Any] | None = None
    reason: str | None = None
    source: str | None = None
    child_id: str | None = None
    child_text: str | None = None


class MutatePdfRequest(BaseModel):
    page_index: int = 0
    block_id: Optional[str] = None
    bbox: Optional[list[float]] = None
    replacement_text: str = ""
    section: Optional[str] = None
    item_id: Optional[str] = None
    child_id: Optional[str] = None
    font_name: Optional[str] = None
    font_size: Optional[float] = None
    is_bold: Optional[bool] = None
    is_italic: Optional[bool] = None
    text_color: Optional[Any] = None


class SaveVersionContentRequest(BaseModel):
    """Full-profile manual save. Replaces version content and recompiles artifacts."""

    content: dict[str, Any]


class ApplyTailoringRequest(BaseModel):
    """Apply whole-document tailored profile to create a new derived version with compiled artifacts."""

    parent_version_id: Optional[str] = None
    version_name: Optional[str] = None
    tailored_profile: dict[str, Any] = Field(default_factory=dict)
    job_description: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    template: Optional[str] = "minimal"
    sections_config: Optional[dict[str, Any]] = None


class MutatePdfResponse(BaseModel):
    version: ResumeVersionResponse
    storage_path: str
    geometry: dict[str, Any]



class RegisterResumeRequest(BaseModel):
    storage_path: str = Field(..., min_length=5, max_length=500)


class UploadResumeResponse(BaseModel):
    resume: ResumeRecordResponse
    parse: Optional[dict[str, Any]] = None
    job_id: Optional[str] = None


class ParseResumeResponse(BaseModel):
    resume_id: str
    version_id: Optional[str] = None
    status: str
    parsed: Optional[dict[str, Any]] = None


class CompletenessResponse(BaseModel):
    score: float
    sections: dict[str, dict[str, Any]]
    recommendations: list[str]


class ResumeListResponse(BaseModel):
    resumes: list[ResumeRecordResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ResumeCreate(BaseModel):
    title: Optional[str] = "Untitled Resume"


class ResumeUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[dict[str, Any]] = None
    meta: Optional[dict[str, Any]] = None


class ResumeProfileUpdate(BaseModel):
    profile: Optional[dict[str, Any]] = None
    meta: Optional[dict[str, Any]] = None


class ParsedPersonal(BaseModel):
    fullName: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    headline: Optional[str] = None
    website: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None


class ParsedExtracted(BaseModel):
    personal: ParsedPersonal = Field(default_factory=ParsedPersonal)
    skills_count: int = 0
    experience_count: int = 0
    projects_count: int = 0
    education_count: int = 0
    certifications_count: int = 0
    internships_count: int = 0
    achievements_count: int = 0
    languages_count: int = 0
