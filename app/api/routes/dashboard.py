"""Dashboard telemetry API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.schemas.dashboard import EMPTY_TELEMETRY, DashboardTelemetryResponse
from app.schemas.common import SuccessResponse
from app.services.dashboard_service import DashboardService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


import time

_DASHBOARD_CACHE: dict[str, tuple[dict[str, Any], float]] = {}


def clear_dashboard_cache() -> None:
    _DASHBOARD_CACHE.clear()


@router.get(
    "",
    response_model=SuccessResponse[DashboardTelemetryResponse],
    summary="Get dashboard telemetry",
    description="Return aggregated user metrics for the Command Center dashboard with 30s caching.",
)
async def get_dashboard_telemetry(
    no_cache: bool = False,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[DashboardTelemetryResponse]:
    """Return aggregated telemetry with 30s per-user cache and per-section error isolation."""
    now = time.time()
    if not no_cache:
        cached = _DASHBOARD_CACHE.get(auth.user.id)
        if cached and (now - cached[1]) < 30.0:
            return SuccessResponse(data=DashboardTelemetryResponse(**cached[0]))

    try:
        service = DashboardService(supabase=auth.supabase)
        data = await service.get_user_telemetry(auth.user.id)

        # 1. Section: Top Recommendations (isolated)
        try:
            from app.services.recommendations.recommendation_engine import RecommendationEngine
            engine = RecommendationEngine(client=auth.supabase)
            recs = engine.get_recommendations(user_id=auth.user.id, limit=5)
            data["top_recommendations"] = recs if isinstance(recs, list) else []
        except Exception as exc:
            logger.debug("Dashboard recommendations section skipped: %s", exc)
            data["top_recommendations"] = []

        # 2. Section: Saved jobs (isolated)
        try:
            res = auth.supabase.table("saved_jobs").select("job_id, jobs(*)").eq("user_id", auth.user.id).limit(5).execute()
            raw_saved = getattr(res, "data", None) or []
            data["saved_jobs"] = [r.get("jobs") for r in raw_saved if r.get("jobs")]
        except Exception as exc:
            logger.debug("Dashboard saved_jobs section skipped: %s", exc)
            data["saved_jobs"] = []

        # 3. Section: Recent jobs (isolated)
        try:
            j_res = auth.supabase.table("jobs").select("id, title, company, location, posted_at, created_at").eq("is_active", True).order("created_at", desc=True).limit(5).execute()
            data["recent_jobs"] = getattr(j_res, "data", None) or []
        except Exception as exc:
            logger.debug("Dashboard recent_jobs section skipped: %s", exc)
            data["recent_jobs"] = []

        _DASHBOARD_CACHE[auth.user.id] = (data, now)
        return SuccessResponse(data=DashboardTelemetryResponse(**data))
    except Exception:
        logger.exception("Dashboard telemetry endpoint failed; returning empty payload")
        return SuccessResponse(data=DashboardTelemetryResponse(**dict(EMPTY_TELEMETRY)))
