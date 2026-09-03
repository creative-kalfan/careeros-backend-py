"""Resume template data models for the CareerOS Resume Module (Step 2)."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ResumeTemplate(BaseModel):
    """Resume template metadata stored in the database."""

    id: Optional[str] = None
    slug: str
    name: str
    description: Optional[str] = None
    source_repository: Optional[str] = None
    source_url: Optional[str] = None
    author: Optional[str] = None
    license: Optional[str] = None
    license_url: Optional[str] = None
    attribution_required: bool = False
    modification_allowed: bool = True
    redistribution_allowed: bool = True
    layout_type: str = "single-column"
    column_count: int = 1
    page_preference: str = "one-page"
    ats_characteristics: dict[str, Any] = Field(default_factory=dict)
    target_roles: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    target_experience_levels: list[str] = Field(default_factory=list)
    evidence_type: Optional[str] = None
    evidence_description: Optional[str] = None
    preview_url: Optional[str] = None
    template_path: str
    status: str = "active"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_db_row(cls, row: dict[str, Any] | None) -> "ResumeTemplate | None":
        if not row:
            return None
        return cls.model_validate(row)


class ResumeTemplateCreate(BaseModel):
    slug: str
    name: str
    description: Optional[str] = None
    source_repository: Optional[str] = None
    source_url: Optional[str] = None
    author: Optional[str] = None
    license: Optional[str] = None
    license_url: Optional[str] = None
    attribution_required: bool = False
    modification_allowed: bool = True
    redistribution_allowed: bool = True
    layout_type: str = "single-column"
    column_count: int = 1
    page_preference: str = "one-page"
    ats_characteristics: dict[str, Any] = Field(default_factory=dict)
    target_roles: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    target_experience_levels: list[str] = Field(default_factory=list)
    evidence_type: Optional[str] = None
    evidence_description: Optional[str] = None
    preview_url: Optional[str] = None
    template_path: str
    status: str = "active"


class ResumeTemplateUpdate(BaseModel):
    slug: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    source_repository: Optional[str] = None
    source_url: Optional[str] = None
    author: Optional[str] = None
    license: Optional[str] = None
    license_url: Optional[str] = None
    attribution_required: Optional[bool] = None
    modification_allowed: Optional[bool] = None
    redistribution_allowed: Optional[bool] = None
    layout_type: Optional[str] = None
    column_count: Optional[int] = None
    page_preference: Optional[str] = None
    ats_characteristics: Optional[dict[str, Any]] = None
    target_roles: Optional[list[str]] = None
    target_industries: Optional[list[str]] = None
    target_experience_levels: Optional[list[str]] = None
    evidence_type: Optional[str] = None
    evidence_description: Optional[str] = None
    preview_url: Optional[str] = None
    template_path: Optional[str] = None
    status: Optional[str] = None
