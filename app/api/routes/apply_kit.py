"""Apply kit API routes."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.auth.service import AuthContext
from app.config import get_settings
from app.dependencies import get_current_user
from app.schemas.common import SuccessResponse
from app.services.resumes.apply_kit_service import ApplyKitService

router = APIRouter(prefix="/api/apply-kit", tags=["apply-kit"])


class ApplyKitRequest(BaseModel):
    job_id: str = Field(description="Target job ID")
    resume_id: str = Field(description="Candidate resume ID")


@router.post("/generate", response_model=SuccessResponse[dict])
async def generate_apply_kit(
    body: ApplyKitRequest,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Generate an evidence-locked apply kit (cover letter, standard answers, export text)."""
    settings = get_settings()
    if not getattr(settings, "apply_kit_enabled", False):
        return SuccessResponse(data={
            "enabled": False,
            "message": "Apply kit feature is currently disabled.",
            "requires_human_review": True,
        })

    service = ApplyKitService()
    data = await service.generate_apply_kit(
        user_id=auth.user.id,
        job_id=body.job_id,
        resume_id=body.resume_id,
        auth_client=auth.supabase,
    )
    return SuccessResponse(data=data)


@router.get("/export/{job_id}/{resume_id}/txt")
async def export_apply_kit_txt(
    job_id: str,
    resume_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> Response:
    """Export the apply kit as a plain text bundle."""
    service = ApplyKitService()
    data = await service.generate_apply_kit(
        user_id=auth.user.id,
        job_id=job_id,
        resume_id=resume_id,
        auth_client=auth.supabase,
    )
    bundle_text = data.get("bundle_text", "")
    return Response(
        content=bundle_text,
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename=apply_kit_{job_id[:8]}.txt"},
    )
