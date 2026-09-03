"""Resume template API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.repositories.resume_template_repository import ResumeTemplateRepository
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.resume_template import ResumeTemplateListResponse, ResumeTemplateResponse

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _to_response(row: dict[str, Any]) -> ResumeTemplateResponse:
    return ResumeTemplateResponse(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        description=row.get("description"),
        source_repository=row.get("source_repository"),
        source_url=row.get("source_url"),
        author=row.get("author"),
        license=row.get("license"),
        license_url=row.get("license_url"),
        attribution_required=row.get("attribution_required", False),
        modification_allowed=row.get("modification_allowed", True),
        redistribution_allowed=row.get("redistribution_allowed", True),
        layout_type=row.get("layout_type", "single-column"),
        column_count=row.get("column_count", 1),
        page_preference=row.get("page_preference", "one-page"),
        ats_characteristics=row.get("ats_characteristics") or {},
        target_roles=row.get("target_roles") or [],
        target_industries=row.get("target_industries") or [],
        target_experience_levels=row.get("target_experience_levels") or [],
        evidence_type=row.get("evidence_type"),
        evidence_description=row.get("evidence_description"),
        preview_url=row.get("preview_url"),
        template_path=row.get("template_path", ""),
        status=row.get("status", "active"),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
    )


@router.get(
    "",
    response_model=SuccessResponse[ResumeTemplateListResponse],
    responses={401: {"model": ErrorResponse}},
)
async def list_templates(
    page: int = 1,
    page_size: int = 20,
) -> SuccessResponse[ResumeTemplateListResponse]:
    """List all active resume templates (public)."""
    repo = ResumeTemplateRepository()
    rows = repo.list_templates(status="active")
    records = [_to_response(r) for r in rows]
    total = len(records)
    total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1
    start = (page - 1) * page_size
    end = start + page_size
    return SuccessResponse(
        data=ResumeTemplateListResponse(
            templates=records[start:end],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
    )


@router.get(
    "/{template_id}",
    response_model=SuccessResponse[ResumeTemplateResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_template(
    template_id: str,
) -> SuccessResponse[ResumeTemplateResponse]:
    """Get a single active resume template by id or slug (public)."""
    repo = ResumeTemplateRepository()
    row = repo.get_template_by_id(template_id)
    if not row:
        row = repo.get_template_by_slug(template_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return SuccessResponse(data=_to_response(row))
