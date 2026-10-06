"""Market demand API routes."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Query

from app.auth.service import AuthContext
from app.config import get_settings
from app.dependencies import get_current_user
from app.schemas.common import SuccessResponse
from app.services.market_demand.service import MarketDemandService

router = APIRouter(prefix="/api/market-demand", tags=["market-demand"])


@router.get("", response_model=SuccessResponse[dict])
async def get_market_demand(
    role_family: str = Query("Software Engineering", description="Role family name to analyze"),
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Get market demand trends, sample size, fresher share, and skill-gap roadmap."""
    settings = get_settings()
    # If feature flag is off, degrade gracefully
    if not getattr(settings, "market_demand_enabled", False):
        return SuccessResponse(data={
            "enabled": False,
            "message": "Market demand dashboard is currently disabled.",
            "role_family": role_family,
            "sample_size": 0,
            "top_skills": [],
            "skill_gap": [],
            "learning_roadmap": [],
        })

    service = MarketDemandService()
    data = await service.get_market_demand(
        role_family=role_family,
        user_id=auth.user.id,
        auth_client=auth.supabase,
    )
    return SuccessResponse(data=data)
