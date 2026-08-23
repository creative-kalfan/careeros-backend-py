"""Notifications API routes.

Thin HTTP layer — delegates to NotificationService (engine + repository).
Response shapes preserve the existing frontend contract:
    { success: true, data: { notifications: [...] } }
    { success: true, data: { notification: {...} } }
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.schemas.common import ErrorResponse, SuccessResponse
from app.services.notifications.notification_service import NotificationService

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
    service = NotificationService()
    data = await service.list_notifications(
        auth,
        is_read=isRead,
        channel=channel,
        type=type,
        limit=limit or 50,
    )
    return SuccessResponse(data=data)


@router.get(
    "/unread",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def list_unread_notifications(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """List unread notifications for the authenticated user."""
    service = NotificationService()
    data = await service.list_notifications(auth, is_read=False)
    return SuccessResponse(data=data)


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

    service = NotificationService()
    try:
        data = await service.mark_read(auth, notification_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Notification not found")

    if not data.get("notification"):
        raise HTTPException(status_code=404, detail="Notification not found")

    return SuccessResponse(data=data)


@router.post(
    "/read-all",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def mark_all_notifications_read(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Mark all notifications as read."""
    service = NotificationService()
    data = await service.mark_all_read(auth)
    return SuccessResponse(data=data)


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
    service = NotificationService()
    deleted = await service.delete_notification(auth, notification_id)
    return SuccessResponse(data={"id": notification_id, "deleted": deleted})
