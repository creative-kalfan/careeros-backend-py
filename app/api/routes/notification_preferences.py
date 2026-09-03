"""Notification preferences API routes.

Thin HTTP layer — delegates to NotificationService. Response shapes follow
the existing frontend contract:
    { success: true, data: { preferences: {...} } }
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.schemas.common import ErrorResponse, SuccessResponse
from app.services.notifications.notification_service import NotificationService

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
    service = NotificationService()
    prefs = await service.get_preferences(auth)
    return SuccessResponse(data={"preferences": prefs})


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
    service = NotificationService()
    try:
        prefs = await service.update_preferences(auth, body)
    except ValueError:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Failed to update preferences") from exc
    return SuccessResponse(data={"preferences": prefs})
