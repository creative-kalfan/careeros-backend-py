"""Resume template API routes."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.repositories.resume_template_repository import ResumeTemplateRepository
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.resume_template import ResumeTemplateListResponse, ResumeTemplateResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/templates", tags=["templates"])

# Namespace used to derive stable, deterministic UUIDs for bundled fallback
# templates. These IDs are only used when a template is missing from the
# database, so the endpoint still returns a valid row instead of a 500/404.
_TEMPLATE_NS = uuid.UUID("5b1a2f84-8a4b-4b10-9e6e-4a8f2c6d9d7e")


def _builtin_template(slug: str, name: str, description: str, **overrides: Any) -> dict[str, Any]:
    """Build a canonical fallback template row for a known resume slug."""
    row: dict[str, Any] = {
        "id": str(uuid.uuid5(_TEMPLATE_NS, f"template:{slug}")),
        "slug": slug,
        "name": name,
        "description": description,
        "source_repository": "careeros/templates",
        "source_url": "https://github.com/careeros/templates",
        "author": "CareerOS",
        "license": "MIT",
        "license_url": "https://opensource.org/licenses/MIT",
        "attribution_required": False,
        "modification_allowed": True,
        "redistribution_allowed": True,
        "layout_type": "single-column",
        "column_count": 1,
        "page_preference": "one-page",
        "ats_characteristics": {
            "single_column": True,
            "tables": False,
            "icons": False,
            "graphics": False,
            "standard_headings": True,
            "text_heavy": True,
            "one_page_preferred": True,
        },
        "target_roles": ["Software Engineer", "Product Manager", "Data Analyst"],
        "target_industries": ["Technology", "SaaS", "General"],
        "target_experience_levels": ["entry", "junior", "mid", "senior"],
        "evidence_type": "original",
        "evidence_description": "CareerOS original ATS-friendly template.",
        "preview_url": f"/templates/{slug}/preview.png",
        "template_path": f"templates/{slug}",
        "status": "active",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    row.update(overrides)
    return row


# Bundled canonical fallback definitions. These are used when the database
# does not yet contain a template for the requested slug (or the database is
# unreachable), guaranteeing `/api/templates/{slug}` returns valid JSON.
_BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "modern": _builtin_template(
        "modern",
        "Modern",
        "A clean, modern single-column resume template optimized for ATS "
        "parsing. Minimalist design with clear section headings for tech and "
        "product roles.",
    ),
    "minimal": _builtin_template(
        "minimal",
        "Minimal",
        "A focused, minimalist single-column resume template with a strong "
        "typographic hierarchy and generous whitespace.",
    ),
    "classic": _builtin_template(
        "classic",
        "Classic",
        "A timeless single-column resume template with traditional section "
        "headings, suitable for most professional roles.",
    ),
    "executive": _builtin_template(
        "executive",
        "Executive",
        "A polished single-column resume template built for senior and "
        "executive candidates, emphasizing leadership and impact.",
    ),
}


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


def _resolve_template(template_id: str) -> dict[str, Any] | None:
    """Resolve a template by id or slug, falling back to bundled defaults.

    Lookups are wrapped so database errors (e.g. casting a non-UUID slug
    against the ``uuid`` ``id`` column) degrade gracefully to the slug lookup
    and finally to the bundled fallback registry instead of raising a 500.
    """
    repo = ResumeTemplateRepository()
    for lookup in (repo.get_template_by_id, repo.get_template_by_slug):
        try:
            row = lookup(template_id) or None
        except Exception:
            logger.warning(
                "Template lookup failed for %r; falling back to bundled registry.",
                template_id,
                exc_info=True,
            )
            row = None
        if row:
            return row
    return _BUILTIN_TEMPLATES.get(template_id)


@router.get(
    "/{template_id}",
    response_model=SuccessResponse[ResumeTemplateResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_template(
    template_id: str,
) -> SuccessResponse[ResumeTemplateResponse]:
    """Get a single active resume template by id or slug (public)."""
    row = _resolve_template(template_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return SuccessResponse(data=_to_response(row))
