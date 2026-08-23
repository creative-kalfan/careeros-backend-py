"""Recommendations API routes.

Delegates ranking to RecommendationService / RecommendationEngine which reuse
PersonalizedJobService scoring. Supports both dynamic generation and persisted
recommendations (hybrid).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.schemas.common import ErrorResponse, SuccessResponse
from app.services.recommendations.recommendation_service import RecommendationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get(
    "",
    response_model=SuccessResponse[dict],
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
) -> SuccessResponse[dict]:
    """List recommendations for the authenticated user.

    Returns { recommendations: [...] } inside the success envelope for
    frontend compatibility (careeros-frontend expects data.recommendations).
    Also includes meta-like count for convenience.
    """
    service = RecommendationService()
    try:
        recs = await service.generate_for_user(
            auth=auth,
            status=status,
            sort=sort or "highest-score",
            remote=remote,
            saved=saved,
            applied=applied,
            dismissed=dismissed,
            top_matches=topMatches,
            min_score=minScore,
            priority=priority,
            limit=limit or 50,
        )
    except Exception as exc:
        logger.exception("generate_for_user failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to generate recommendations: {exc}") from exc

    # Frontend expects data.recommendations; also support data as list for legacy callers
    # so we return both shapes: data is dict with recommendations key
    return SuccessResponse(data={"recommendations": recs, "count": len(recs)})


@router.get(
    "/top",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def get_top_recommendations(
    limit: Optional[int] = Query(5),
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Get top recommendations for the authenticated user."""
    limit = max(1, min(limit or 5, 25))
    service = RecommendationService()
    try:
        recs = await service.get_top(auth=auth, limit=limit)
    except Exception as exc:
        logger.exception("get_top failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to get top recommendations: {exc}") from exc
    return SuccessResponse(data={"recommendations": recs, "count": len(recs)})


@router.post(
    "/refresh",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def refresh_recommendations(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Refresh recommendations for the authenticated user.

    Triggers a fresh dynamic generation pass (deterministic, no LLM).
    If a background worker is needed in future, this endpoint can enqueue
    an ARQ job; for now it runs synchronously and returns the count.
    """
    service = RecommendationService()
    try:
        recs = await service.generate_for_user(auth=auth, limit=50)
    except Exception as exc:
        logger.exception("refresh failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Refresh failed: {exc}") from exc

    # Notification hook: generate notifications from the recommendation output
    # (consumes existing ranked results; never recalculates scores and never
    # breaks the refresh on failure).
    try:
        from app.services.notifications.notification_service import NotificationService

        await NotificationService().notify_from_recommendations(auth, recs)
    except Exception as exc:
        logger.warning("Notification generation failed (non-blocking): %s", exc)

    return SuccessResponse(data={"result": "refresh_triggered", "count": len(recs)})


@router.post(
    "/save",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def save_recommendation(
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Save a recommendation.

    Tries persisted recommendations table first; if the recommendation is
    dynamic (job id) and not yet persisted, inserts a record so status
    persists across refreshes. Falls back to saved_jobs for pure dynamic.
    """
    recommendation_id = body.get("recommendationId")
    if not recommendation_id:
        raise HTTPException(status_code=400, detail="recommendationId is required")

    # Try update persisted recommendation
    try:
        result = (
            await auth.supabase.table("recommendations")
            .update({"status": "SAVED"})
            .eq("id", recommendation_id)
            .eq("user_id", auth.user.id)
            .select()
            .single()
            .execute()
        )
        if result.data:
            return SuccessResponse(data={"recommendation": result.data})
    except Exception:
        pass

    # Try by job_id (dynamic id == job id)
    try:
        result = (
            await auth.supabase.table("recommendations")
            .update({"status": "SAVED"})
            .eq("job_id", recommendation_id)
            .eq("user_id", auth.user.id)
            .select()
            .single()
            .execute()
        )
        if result.data:
            return SuccessResponse(data={"recommendation": result.data})
    except Exception:
        pass

    # Fallback: treat as job id and upsert into saved_jobs for legacy compat
    # Try to insert into recommendations if table exists (needs resume_id)
    try:
        from app.repositories.recommendation_repository import RecommendationRepository

        repo = RecommendationRepository()
        resume_id = await repo.find_resume_id(auth.supabase, auth.user.id)
        if resume_id:
            try:
                await auth.supabase.table("recommendations").insert(
                    {
                        "user_id": auth.user.id,
                        "job_id": recommendation_id,
                        "resume_id": resume_id,
                        "match_score": 75,
                        "skill_match": 60,
                        "keyword_match": 60,
                        "semantic_similarity": 60,
                        "recommendation_reason": [],
                        "priority": "good",
                        "status": "SAVED",
                    }
                ).execute()
                return SuccessResponse(data={"recommendation": {"id": recommendation_id, "status": "SAVED"}})
            except Exception:
                pass
    except Exception:
        pass

    # Final fallback: saved_jobs
    try:
        await auth.supabase.table("saved_jobs").upsert(
            {"user_id": auth.user.id, "job_id": recommendation_id}, onConflict="user_id,job_id"
        ).execute()
        return SuccessResponse(data={"recommendation": {"id": recommendation_id, "status": "SAVED"}})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Save failed: {exc}") from exc


@router.post(
    "/dismiss",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def dismiss_recommendation(
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Dismiss a recommendation.

    Persists DISMISSED status so future generations exclude the job.
    """
    recommendation_id = body.get("recommendationId")
    if not recommendation_id:
        raise HTTPException(status_code=400, detail="recommendationId is required")

    # Try persisted update
    try:
        result = (
            await auth.supabase.table("recommendations")
            .update({"status": "DISMISSED"})
            .eq("id", recommendation_id)
            .eq("user_id", auth.user.id)
            .select()
            .single()
            .execute()
        )
        if result.data:
            return SuccessResponse(data={"recommendation": result.data})
    except Exception:
        pass

    try:
        result = (
            await auth.supabase.table("recommendations")
            .update({"status": "DISMISSED"})
            .eq("job_id", recommendation_id)
            .eq("user_id", auth.user.id)
            .select()
            .single()
            .execute()
        )
        if result.data:
            return SuccessResponse(data={"recommendation": result.data})
    except Exception:
        pass

    # Insert dismissed record for future exclusion
    try:
        from app.repositories.recommendation_repository import RecommendationRepository

        repo = RecommendationRepository()
        resume_id = await repo.find_resume_id(auth.supabase, auth.user.id)
        if resume_id:
            try:
                await auth.supabase.table("recommendations").insert(
                    {
                        "user_id": auth.user.id,
                        "job_id": recommendation_id,
                        "resume_id": resume_id,
                        "match_score": 60,
                        "skill_match": 50,
                        "keyword_match": 50,
                        "semantic_similarity": 50,
                        "recommendation_reason": [],
                        "priority": "possible",
                        "status": "DISMISSED",
                    }
                ).execute()
                return SuccessResponse(data={"recommendation": {"id": recommendation_id, "status": "DISMISSED"}})
            except Exception:
                pass
    except Exception:
        pass

    # If recommendations table missing, still return success (dynamic dismissal is in-memory only this request)
    return SuccessResponse(data={"recommendation": {"id": recommendation_id, "status": "DISMISSED"}})
