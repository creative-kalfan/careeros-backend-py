"""Notifications API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.schemas.common import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def list_notifications(
    isRead: Optional[bool] = Query(None),
    channel: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: Optional[int] = Query(50),
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """List notifications for the authenticated user."""
    query = (
        auth.supabase.table("notifications")
        .select("*")
        .eq("user_id", auth.user.id)
        .order("created_at", ascending=False)
        .limit(min(limit, 100))
    )

    if isRead is not None:
        query = query.eq("is_read", isRead)

    if channel:
        query = query.eq("delivery_channel", channel)

    if type:
        query = query.eq("type", type)

    result = query.execute()
    return SuccessResponse(data={"notifications": result.data or []})


@router.get(
    "/unread",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def list_unread_notifications(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """List unread notifications for the authenticated user."""
    result = (
        auth.supabase.table("notifications")
        .select("*")
        .eq("user_id", auth.user.id)
        .eq("is_read", False)
        .order("created_at", ascending=False)
        .execute()
    )
    return SuccessResponse(data={"notifications": result.data or []})


@router.post(
    "/read",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def mark_notification_read(
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Mark a notification as read."""
    notification_id = body.get("notificationId")
    if not notification_id:
        raise HTTPException(status_code=400, detail="notificationId is required")

    result = (
        auth.supabase.table("notifications")
        .update({"is_read": True, "read_at": datetime.utcnow().isoformat()})
        .eq("id", notification_id)
        .eq("user_id", auth.user.id)
        .select()
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Notification not found")

    return SuccessResponse(data={"notification": result.data})


@router.post(
    "/read-all",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def mark_all_notifications_read(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Mark all notifications as read."""
    auth.supabase.table("notifications").update({"is_read": True, "read_at": datetime.utcnow().isoformat()}).eq("user_id", auth.user.id).execute()
    return SuccessResponse(data={"notifications": []})


@router.delete(
    "/{notification_id}",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def delete_notification(
    notification_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Delete a notification."""
    result = (
        auth.supabase.table("notifications")
        .delete()
        .eq("id", notification_id)
        .eq("user_id", auth.user.id)
        .execute()
    )
    return SuccessResponse(data={"id": notification_id, "deleted": True})
