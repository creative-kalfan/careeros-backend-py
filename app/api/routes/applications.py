"""Applications API routes."""

from __future__ import annotations

from typing import Annotated, Optional

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta

router = APIRouter(prefix="/applications", tags=["applications"])


# ── Fixed-path routes MUST come before /{application_id} parameterized routes ──


@router.get(
    "",
    response_model=SuccessResponse[list[dict]],
    responses={401: {"model": ErrorResponse}},
)
async def list_applications(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Optional[str] = None,
    search: Optional[str] = None,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[list[dict]]:
    """List all applications for the authenticated user."""
    query = (
        auth.supabase.table("applications")
        .select("*", count="exact")
        .eq("user_id", auth.user.id)
    )

    if status:
        query = query.eq("status", status)

    if search:
        search_term = f"%{search}%"
        query = query.or_(
            f"job_title.ilike.{search_term},company_name.ilike.{search_term}"
        )

    query = query.order("application_date", desc=True)
    offset = (page - 1) * page_size
    query = query.range(offset, offset + page_size - 1)

    result = await query.execute()

    total = result.count if hasattr(result, "count") and result.count is not None else len(result.data or [])

    return SuccessResponse(
        data=result.data or [],
        meta=build_meta(page, page_size, total),
    )


@router.get(
    "/stats",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def get_application_stats(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Get aggregate statistics for the authenticated user's applications."""
    result = await (
        auth.supabase.table("applications")
        .select("id, status, application_date")
        .eq("user_id", auth.user.id)
        .execute()
    )

    applications = result.data or []
    total = len(applications)

    by_status: dict[str, int] = {
        "applied": 0,
        "assessment": 0,
        "interview": 0,
        "offer": 0,
        "rejected": 0,
    }

    for app in applications:
        status = app.get("status", "")
        if status in by_status:
            by_status[status] += 1

    with_interviews = by_status["interview"] + by_status["offer"]
    with_offers = by_status["offer"]
    active_count = total - by_status["rejected"]
    success_rate = round((active_count / total) * 100) if total > 0 and active_count > 0 else None
    interview_rate = round((with_interviews / total) * 100) if total > 0 else 0
    offer_rate = round((with_offers / with_interviews) * 100) if with_interviews > 0 else 0

    stats = {
        "total": total,
        "byStatus": by_status,
        "applied": by_status["applied"],
        "assessment": by_status["assessment"],
        "interview": by_status["interview"],
        "offer": by_status["offer"],
        "rejected": by_status["rejected"],
        "successRate": success_rate,
        "interviewRate": interview_rate,
        "offerRate": offer_rate,
        "averageResponseDays": None,
    }

    return SuccessResponse(data=stats)


@router.post(
    "",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def create_application(
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Create a new application."""
    job_title = body.get("job_title")
    company_name = body.get("company_name")
    notes = body.get("notes")

    if not job_title or not company_name:
        raise HTTPException(status_code=400, detail="job_title and company_name are required")

    result = await (
        auth.supabase.table("applications")
        .insert({
            "user_id": auth.user.id,
            "job_title": job_title,
            "company_name": company_name,
            "notes": notes,
            "status": "applied",
            "application_date": datetime.utcnow().isoformat(),
        })
        .execute()
    )
    rows = result.data or []
    data = rows[0] if isinstance(rows, list) and rows else (result.data or {})
    return SuccessResponse(data=data, status_code=201)


# ── Parameterized /{application_id} routes below ──


@router.get(
    "/{application_id}",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_application(
    application_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Get a single application by ID."""
    result = await (
        auth.supabase.table("applications")
        .select("*")
        .eq("id", application_id)
        .eq("user_id", auth.user.id)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Application not found")

    return SuccessResponse(data=rows[0] if isinstance(rows, list) else result.data)


@router.patch(
    "/{application_id}",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def update_application(
    application_id: str,
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Update an application."""
    updates = {k: v for k, v in body.items() if k in {"status", "notes", "job_title", "company_name"}}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    result = await (
        auth.supabase.table("applications")
        .update(updates)
        .eq("id", application_id)
        .eq("user_id", auth.user.id)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Application not found")

    return SuccessResponse(data=rows[0] if isinstance(rows, list) else result.data)


@router.delete(
    "/{application_id}",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def delete_application(
    application_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Delete an application."""
    result = await (
        auth.supabase.table("applications")
        .delete()
        .eq("id", application_id)
        .eq("user_id", auth.user.id)
        .execute()
    )
    return SuccessResponse(data={"id": application_id, "deleted": True})
