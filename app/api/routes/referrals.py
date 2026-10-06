"""Referral Assistant API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.auth.service import AuthContext
from app.config import get_settings
from app.dependencies import get_current_user
from app.schemas.common import SuccessResponse
from app.services.referrals.service import ReferralAssistantService

router = APIRouter(prefix="/api/referrals", tags=["referrals"])


@router.post("/upload-csv", response_model=SuccessResponse[dict])
async def upload_connections_csv(
    file: UploadFile = File(...),
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Upload LinkedIn Connections CSV (emails and phone numbers are stripped automatically)."""
    settings = get_settings()
    if not getattr(settings, "referral_assistant_enabled", False):
        return SuccessResponse(data={"enabled": False, "message": "Referral assistant feature is disabled."})

    contents = await file.read()
    try:
        csv_text = contents.decode("utf-8")
    except UnicodeDecodeError:
        csv_text = contents.decode("latin-1")

    service = ReferralAssistantService()
    result = await service.import_connections(auth.user.id, csv_text, auth.supabase)
    return SuccessResponse(data=result)


@router.get("/match", response_model=SuccessResponse[list[dict]])
async def find_company_referrals(
    company: str = Query(..., description="Target company name"),
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[list[dict]]:
    """Find candidate's connections at a target company."""
    service = ReferralAssistantService()
    matches = await service.find_referrals_for_job(auth.user.id, company, auth.supabase)
    return SuccessResponse(data=matches)


@router.delete("/all", response_model=SuccessResponse[dict])
async def delete_all_connections(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """One-click delete all stored referral connections for the authenticated user."""
    service = ReferralAssistantService()
    count = await service.delete_all_connections(auth.user.id, auth.supabase)
    return SuccessResponse(data={"deleted": count})
