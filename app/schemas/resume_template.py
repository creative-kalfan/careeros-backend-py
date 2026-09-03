"""Resume template API schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(snake_str: str) -> str:
    """Convert snake_case to camelCase."""
    components = snake_str.split("_")
    return components[0] + "".join(p.title() for p in components[1:])


class ResumeTemplateResponse(BaseModel):
    """Shape returned for a resume template row."""

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=_to_camel,
    )

    id: str
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
    created_at: str
    updated_at: str


class ResumeTemplateListResponse(BaseModel):
    """Shape returned for a paginated list of resume templates."""

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=_to_camel,
    )

    templates: list[ResumeTemplateResponse]
    total: int
    page: int
    page_size: int = Field(..., alias="pageSize")
    total_pages: int = Field(..., alias="totalPages")
