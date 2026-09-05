"""Interview Preparation API routes.

Routes are kept thin: all business logic (context gathering, LLM
generation, grounding validation, ownership, staleness) lives in
:class:`InterviewPrepService`. Repositories own persistence.
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.models.interview_prep import InterviewPrepGenerateRequest, InterviewPrepQuestionUpdate
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.services.interview_prep.service import InterviewPrepService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/interview-prep", tags=["interview-prep"])

SERVICE = InterviewPrepService()


@router.post(
    "/generate",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    status_code=http_status.HTTP_201_CREATED,
)
async def generate_preparation(
    payload: InterviewPrepGenerateRequest,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Generate an interview preparation session for an application/interview."""
    if not payload.application_id:
        raise HTTPException(status_code=400, detail="application_id is required")
    try:
        session = await SERVICE.generate(
            auth,
            application_id=payload.application_id,
            interview_id=payload.interview_id,
            resume_id=payload.resume_id,
            job_id=payload.job_id,
            question_count=payload.question_count,
            async_mode=payload.async_mode,
        )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — never leak internals
        logger.exception("Interview prep generation failed")
        raise HTTPException(status_code=500, detail="Failed to generate interview preparation")
    return SuccessResponse(data=session, status_code=201)


@router.get(
    "/sessions",
    response_model=SuccessResponse[list[dict]],
    responses={401: {"model": ErrorResponse}},
)
async def list_sessions(
    application_id: Optional[str] = Query(None),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[list[dict]]:
    """List preparation sessions for the authenticated user."""
    try:
        result = await SERVICE.list_sessions(
            auth, application_id=application_id, page=page, page_size=page_size
        )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Interview prep list failed")
        raise HTTPException(status_code=500, detail="Failed to list preparation sessions")
    return SuccessResponse(
        data=result["sessions"], meta=build_meta(page, page_size, result["total"])
    )


@router.get(
    "/sessions/{session_id}",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_session(
    session_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Get a preparation session with questions and live staleness state."""
    try:
        return SuccessResponse(data=await SERVICE.session_with_staleness(auth, session_id))
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Interview prep detail failed")
        raise HTTPException(status_code=500, detail="Failed to load preparation session")


@router.post(
    "/sessions/{session_id}/regenerate",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def regenerate_session(
    session_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Regenerate preparation from current source context (bumps version)."""
    try:
        return SuccessResponse(data=await SERVICE.regenerate(auth, session_id))
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Interview prep regeneration failed")
        raise HTTPException(status_code=500, detail="Failed to regenerate preparation")


@router.patch(
    "/questions/{question_id}",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def update_question(
    question_id: str,
    payload: InterviewPrepQuestionUpdate,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Mark a question prepared/bookmarked (real progress, no fake scores)."""
    try:
        return SuccessResponse(
            data=await SERVICE.update_question(auth, question_id, payload.model_dump())
        )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Interview prep question update failed")
        raise HTTPException(status_code=500, detail="Failed to update question")


@router.get(
    "/by-application/{application_id}",
    response_model=SuccessResponse[list[dict]],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def list_by_application(
    application_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[list[dict]]:
    """List preparation sessions attached to one application (Mission Control)."""
    try:
        result = await SERVICE.list_sessions(auth, application_id=application_id)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Interview prep by-application failed")
        raise HTTPException(status_code=500, detail="Failed to list preparation sessions")
    return SuccessResponse(data=result["sessions"])
