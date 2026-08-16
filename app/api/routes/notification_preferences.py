"""Notification preferences API routes."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.schemas.common import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/notification-preferences", tags=["notification-preferences"])


@router.get(
    "",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def get_notification_preferences(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Get notification preferences for the authenticated user."""
    result = (
        auth.supabase.table("notification_preferences")
        .select("*")
        .eq("user_id", auth.user.id)
        .maybe_single()
        .execute()
    )

    if not result.data:
        return SuccessResponse(data={
            "id": None,
            "user_id": auth.user.id,
            "email_enabled": True,
            "in_app_enabled": True,
            "push_enabled": True,
            "high_match_threshold": 80,
            "daily_digest": True,
            "weekly_digest": True,
            "quiet_hours": None,
        })

    return SuccessResponse(data=result.data)


@router.post(
    "",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def update_notification_preferences(
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Update notification preferences for the authenticated user."""
    allowed_fields = {
        "email_enabled",
        "in_app_enabled",
        "push_enabled",
        "high_match_threshold",
        "daily_digest",
        "weekly_digest",
        "quiet_hours",
    }
    updates = {k: v for k, v in body.items() if k in allowed_fields}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    result = (
        auth.supabase.table("notification_preferences")
        .upsert({"user_id": auth.user.id, **updates}, onConflict="user_id")
        .select()
        .single()
        .execute()
    )
    return SuccessResponse(data=result.data or {})
