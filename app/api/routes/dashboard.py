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


@router.get(
    "",
    response_model=SuccessResponse[DashboardTelemetryResponse],
    summary="Get dashboard telemetry",
    description="Return aggregated user metrics for the Command Center dashboard.",
)
async def get_dashboard_telemetry(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[DashboardTelemetryResponse]:
    """Return telemetry with HTTP 200 even when aggregates are empty/failing.

    The service already degrades to safe defaults internally; this outer guard
    covers anything unexpected (e.g. response-model validation) so the
    endpoint never surfaces a 500 for authenticated users.
    """
    try:
        service = DashboardService(supabase=auth.supabase)
        data = await service.get_user_telemetry(auth.user.id)
        return SuccessResponse(data=DashboardTelemetryResponse(**data))
    except Exception:
        logger.exception("Dashboard telemetry endpoint failed; returning empty payload")
        return SuccessResponse(data=DashboardTelemetryResponse(**dict(EMPTY_TELEMETRY)))
