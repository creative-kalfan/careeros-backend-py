"""AI Copilot API routes.

Thin handlers: all context assembly, prompt building, and LLM invocation
live in :class:`CopilotService`. This module only validates auth, delegates,
and maps errors into the standard CareerOS envelope.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.models.copilot import CopilotChatData, CopilotChatRequest
from app.schemas.common import ErrorResponse, SuccessResponse
from app.services.copilot.service import CopilotService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/copilot", tags=["copilot"])

SERVICE = CopilotService()


@router.post(
    "/chat",
    response_model=SuccessResponse[CopilotChatData],
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    status_code=http_status.HTTP_200_OK,
)
async def copilot_chat(
    payload: CopilotChatRequest,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[CopilotChatData]:
    """Chat with the grounded CareerOS Copilot (single JSON response)."""
    try:
        data = await SERVICE.chat(auth, payload.messages, payload.context)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — never leak internals
        logger.exception("Copilot chat failed")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "COPILOT_FAILED",
                "message": "AI assistant failed to respond. Please try again.",
            },
        )
    return SuccessResponse(data=data)
