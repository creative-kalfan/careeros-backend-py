"""Dashboard telemetry API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.schemas.dashboard import DashboardTelemetryResponse
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
    service = DashboardService(supabase=auth.supabase)
    data = await service.get_user_telemetry(auth.user.id)
    return SuccessResponse(data=DashboardTelemetryResponse(**data))
