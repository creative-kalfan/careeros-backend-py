"""Resume export API routes (Step 6)."""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.repositories.resume_repository import ResumeRepository
from app.schemas.common import ErrorResponse, SuccessResponse
from app.services.export_service import export_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get(
    "/resumes/{resume_id}/versions/{version_id}/pdf",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def export_version_pdf(
    resume_id: str,
    version_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    repo = ResumeRepository(jwt=auth.jwt)
    resume = repo.get_resume(auth.user.id, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    version = repo.get_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    if version.get("resume_id") != resume_id:
        raise HTTPException(status_code=400, detail="Version does not belong to this resume")

    from app.models.resume import ResumeContent
    content = ResumeContent.from_dict(version.get("content") or {})
    template = version.get("template", "minimal")

    try:
        pdf_bytes = export_service.export_pdf(content, template)
    except Exception as exc:
        logger.error("PDF export failed: %s", exc)
        raise HTTPException(status_code=500, detail="Unable to generate your resume.") from exc

    name = _sanitize_filename(version.get("version_name") or resume.get("title", "resume"))
    filename = "{name}.pdf".format(name=name)
    from fastapi.responses import Response
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=\"{filename}\""})


@router.get(
    "/resumes/{resume_id}/versions/{version_id}/docx",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def export_version_docx(
    resume_id: str,
    version_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    repo = ResumeRepository(jwt=auth.jwt)
    resume = repo.get_resume(auth.user.id, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    version = repo.get_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    if version.get("resume_id") != resume_id:
        raise HTTPException(status_code=400, detail="Version does not belong to this resume")

    from app.models.resume import ResumeContent
    content = ResumeContent.from_dict(version.get("content") or {})
    template = version.get("template", "minimal")

    try:
        docx_bytes = export_service.export_docx(content, template)
    except Exception as exc:
        logger.error("DOCX export failed: %s", exc)
        raise HTTPException(status_code=500, detail="Unable to generate your resume.") from exc

    name = _sanitize_filename(version.get("version_name") or resume.get("title", "resume"))
    filename = "{name}.docx".format(name=name)
    from fastapi.responses import Response
    return Response(content=docx_bytes, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f"attachment; filename=\"{filename}\""})


def _sanitize_filename(name: str) -> str:
    import re
    cleaned = re.sub(r"[^A-Za-z0-9_\- ]+", "", name)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    return cleaned[:80] or "resume"
