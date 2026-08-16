"""Recommendations API routes."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.schemas.common import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get(
    "",
    response_model=SuccessResponse[list[dict]],
    responses={401: {"model": ErrorResponse}},
)
async def list_recommendations(
    status: Optional[str] = Query(None),
    sort: Optional[str] = Query("highest-score"),
    remote: Optional[bool] = Query(None),
    saved: Optional[bool] = Query(None),
    applied: Optional[bool] = Query(None),
    dismissed: Optional[bool] = Query(None),
    topMatches: Optional[bool] = Query(None),
    minScore: Optional[float] = Query(None),
    priority: Optional[str] = Query(None),
    limit: Optional[int] = Query(50),
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[list[dict]]:
    """List recommendations for the authenticated user."""
    query = (
        auth.supabase.table("recommendations")
        .select("*")
        .eq("user_id", auth.user.id)
    )

    if status:
        query = query.eq("status", status)
    elif saved:
        query = query.eq("status", "SAVED")
    elif applied:
        query = query.eq("status", "APPLIED")
    elif dismissed:
        query = query.eq("status", "DISMISSED")

    if remote is not None:
        query = query.eq("remote", remote)

    if priority:
        query = query.eq("priority", priority)

    if topMatches and minScore is not None:
        query = query.gte("match_score", minScore)

    if sort == "newest":
        query = query.order("created_at", ascending=False)
    else:
        query = query.order("match_score", ascending=False)

    query = query.limit(min(limit, 100))
    result = query.execute()
    return SuccessResponse(data=result.data or [])


@router.get(
    "/top",
    response_model=SuccessResponse[list[dict]],
    responses={401: {"model": ErrorResponse}},
)
async def get_top_recommendations(
    limit: Optional[int] = Query(5),
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[list[dict]]:
    """Get top recommendations for the authenticated user."""
    limit = max(1, min(limit, 25))
    result = (
        auth.supabase.table("recommendations")
        .select("*")
        .eq("user_id", auth.user.id)
        .gte("match_score", 80)
        .order("match_score", ascending=False)
        .limit(limit)
        .execute()
    )
    return SuccessResponse(data=result.data or [])


@router.post(
    "/refresh",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def refresh_recommendations(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Refresh recommendations for the authenticated user."""
    return SuccessResponse(data={"result": "refresh_triggered"})


@router.post(
    "/save",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def save_recommendation(
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Save a recommendation."""
    recommendation_id = body.get("recommendationId")
    if not recommendation_id:
        raise HTTPException(status_code=400, detail="recommendationId is required")

    result = (
        auth.supabase.table("recommendations")
        .update({"status": "SAVED"})
        .eq("id", recommendation_id)
        .eq("user_id", auth.user.id)
        .select()
        .single()
        .execute()
    )
    return SuccessResponse(data=result.data or {})


@router.post(
    "/dismiss",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def dismiss_recommendation(
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Dismiss a recommendation."""
    recommendation_id = body.get("recommendationId")
    if not recommendation_id:
        raise HTTPException(status_code=400, detail="recommendationId is required")

    result = (
        auth.supabase.table("recommendations")
        .update({"status": "DISMISSED"})
        .eq("id", recommendation_id)
        .eq("user_id", auth.user.id)
        .select()
        .single()
        .execute()
    )
    return SuccessResponse(data=result.data or {})
