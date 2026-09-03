"""Resume API routes."""

from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.auth.service import AuthContext
from app.config import get_settings
from app.db.supabase import get_authenticated_client
from app.dependencies import get_current_user
from app.repositories.resume_repository import ResumeRepository
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.resume import (
    CompletenessResponse,
    ParseResumeResponse,
    RegisterResumeRequest,
    ResumeCreate,
    ResumeListResponse,
    ResumeRecordResponse,
    ResumeUpdate,
    UploadResumeResponse,
)
from app.services.resume_parsing import (
    ParseResult,
    ResumeParsingService,
    is_file_too_large,
)
from app.workers.enqueue import enqueue_resume_parse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

# Allowed extensions for resume files
ALLOWED_EXTENSIONS = {".pdf", ".docx"}

# Valid UUID v4 regex (for the filename portion of the storage path).
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _to_record(row: dict[str, Any]) -> ResumeRecordResponse:
    return ResumeRecordResponse(
        id=row["id"],
        user_id=row["user_id"],
        title=row.get("title", "Untitled Resume"),
        file_url=row.get("file_url"),
        original_filename=row.get("original_filename"),
        storage_path=row.get("storage_path"),
        parse_status=row.get("parse_status", "pending"),
        content=row.get("content") or {},
        meta=row.get("meta") or {},
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
    )


def _validate_storage_path(
    user_id: str, storage_path: str
) -> str:
    """Validate that ``storage_path`` belongs to the authenticated user.

    Expected format:

        {authenticated_user_id}/{uuid}.{extension}

    Example:

        c6db4105-73ff-4f86-bf70-09493bad3c82/4b2d7d4a-1234-4567-8901-resume.pdf

    The backend MUST NOT blindly trust the frontend-supplied path.  We verify:

    * exactly two path segments (``user_id/file``) — rejects ``../``,
      extra folders, and bucket prefixes like ``resumes/...``
    * the first segment equals the authenticated user's id
    * the filename is a plain file name with no path separators or
      traversal segments
    * the extension is .pdf or .docx

    Returns the validated filename portion (e.g. ``uuid.pdf``) on success.
    Raises ``HTTPException(400/403)`` otherwise.
    """
    cleaned = storage_path.strip().strip("/")

    # Only ``{user_id}/{filename}`` is allowed — no extra folders.
    if "/" in cleaned:
        parts = cleaned.split("/")
        if len(parts) != 2:
            raise HTTPException(
                status_code=400,
                detail="Storage path must be in the form {user_id}/{filename}",
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="Storage path must be in the form {user_id}/{filename}",
        )

    path_user_id, filename = parts

    # Ownership: first segment must equal the authenticated user.
    if path_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Storage path does not belong to the authenticated user",
        )

    # No path traversal.
    if ".." in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid storage path")

    # Filename must be a valid UUID (idempotency + format enforcement).
    stem = Path(filename).stem
    if not _UUID_RE.match(stem):
        raise HTTPException(status_code=400, detail="Storage filename must be a valid UUID")

    # Extension check.
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Only PDF and DOCX are supported.",
        )

    return filename


def _build_parse_info(
    row: dict[str, Any],
    parse_result: ParseResult | None = None,
) -> dict[str, Any] | None:
    """Build the ``parse`` payload for ``UploadResumeResponse``.

       * If ``parse_result is None``, derive status from the DB row.
       * If parsing completed -> include the extracted counts.
       * If parsing failed -> include the error message.
    """
    status = parse_result.status if parse_result else row.get("parse_status", "pending")
    extracted = None
    error = None
    if parse_result and parse_result.status == "completed":
        extracted = parse_result.extracted
    elif parse_result and parse_result.status == "failed":
        error = parse_result.error
    return {
        "status": status,
        "versionId": None,
        "error": error,
        "extracted": extracted,
    }


@router.get(
    "",
    response_model=SuccessResponse[ResumeListResponse],
    responses={401: {"model": ErrorResponse}},
)
async def list_resumes(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeListResponse]:
    repo = ResumeRepository(jwt=auth.jwt)
    rows = repo.list_resumes(auth.user.id)
    records = [_to_record(r) for r in rows]
    return SuccessResponse(
        data=ResumeListResponse(
            resumes=records,
            total=len(records),
            page=1,
            page_size=len(records) or 20,
            total_pages=1,
        )
    )


@router.post(
    "",
    response_model=SuccessResponse[ResumeRecordResponse],
    responses={401: {"model": ErrorResponse}},
)
async def create_resume(
    body: ResumeCreate,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeRecordResponse]:
    repo = ResumeRepository(jwt=auth.jwt)
    row = repo.create_resume(auth.user.id, title=body.title or "Untitled Resume")
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create resume")
    return SuccessResponse(data=_to_record(row))


@router.get(
    "/{resume_id}",
    response_model=SuccessResponse[ResumeRecordResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_resume(
    resume_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeRecordResponse]:
    repo = ResumeRepository(jwt=auth.jwt)
    row = repo.get_resume(auth.user.id, resume_id)
    if not row:
        raise HTTPException(status_code=404, detail="Resume not found")
    return SuccessResponse(data=_to_record(row))


@router.patch(
    "/{resume_id}",
    response_model=SuccessResponse[ResumeRecordResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def update_resume(
    resume_id: str,
    body: ResumeUpdate,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeRecordResponse]:
    repo = ResumeRepository(jwt=auth.jwt)
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        row = repo.get_resume(auth.user.id, resume_id)
        if not row:
            raise HTTPException(status_code=404, detail="Resume not found")
        return SuccessResponse(data=_to_record(row))

    row = repo.update_resume(auth.user.id, resume_id, update_data)
    if not row:
        raise HTTPException(status_code=404, detail="Resume not found")
    return SuccessResponse(data=_to_record(row))


@router.delete(
    "/{resume_id}",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def delete_resume(
    resume_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    repo = ResumeRepository(jwt=auth.jwt)
    ok = repo.delete_resume(auth.user.id, resume_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Resume not found")
    return SuccessResponse(data={"deleted": True})


@router.post(
    "/register",
    response_model=SuccessResponse[UploadResumeResponse],
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def register_resume(
    body: RegisterResumeRequest,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[UploadResumeResponse]:
    """Register a resume that has already been uploaded to Supabase Storage.

    The browser uploads the file directly to the ``resumes`` bucket using
    the authenticated supabase-js client, then sends ONLY the storage path
    here. We validate ownership, create the database record, enqueue a
    background ARQ job for parsing, and return immediately.

    Idempotent: if this ``storage_path`` is already registered for this user
    (e.g. due to a timeout + retry), we return the existing record instead of
    creating a duplicate.
    """
    storage_path = body.storage_path.strip()
    logger.info(
        "REGISTER REQUEST user=%s storage_path=%s",
        auth.user.id,
        storage_path,
    )

    # 1. Validate storage_path ownership + format.
    filename = _validate_storage_path(auth.user.id, storage_path)
    logger.info("REGISTER STORAGE VALIDATED user=%s filename=%s", auth.user.id, filename)

    repo = ResumeRepository(jwt=auth.jwt)

    # 2. Idempotency — return existing resume if this storage_path is known.
    existing = repo.find_by_storage_path(auth.user.id, storage_path)
    if existing:
        logger.info(
            "REGISTER IDEMPOTENT HIT user=%s resume_id=%s",
            auth.user.id,
            existing["id"],
        )
        record = _to_record(existing)
        parse_info = _build_parse_info(existing)
        return SuccessResponse(
            data=UploadResumeResponse(resume=record, parse=parse_info)
        )

    # 3. Create the resume database record (lightweight — no file download).
    row = repo.create_resume(
        user_id=auth.user.id,
        title=Path(filename).stem or "Untitled Resume",
        original_filename=filename,
        storage_path=storage_path,
    )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create resume record")

    resume_id = row["id"]
    logger.info("REGISTER RECORD CREATED user=%s resume_id=%s", auth.user.id, resume_id)

    # 4. Enqueue background parsing job.
    try:
        job_id = await enqueue_resume_parse(resume_id, auth.user.id, storage_path)
    except Exception as exc:
        logger.exception(
            "REGISTER ENQUEUE FAILED user=%s resume_id=%s error=%s",
            auth.user.id,
            resume_id,
            exc,
        )
        repo.update_resume(
            auth.user.id,
            resume_id,
            {
                "parse_status": "failed",
                "meta": {"parse_error": "Failed to enqueue parsing job"},
            },
        )
        raise HTTPException(
            status_code=500,
            detail="Your file was registered, but we couldn't start parsing. Please try again.",
        )

    logger.info(
        "REGISTER ENQUEUED user=%s resume_id=%s job_id=%s",
        auth.user.id,
        resume_id,
        job_id,
    )

    # 5. Return immediately — parsing happens in the background.
    final_row = repo.get_resume(auth.user.id, resume_id) or row
    record = _to_record(final_row)
    parse_info = _build_parse_info(final_row)
    parse_info["job_id"] = job_id

    logger.info(
        "REGISTER COMPLETE user=%s resume_id=%s parse_status=%s job_id=%s",
        auth.user.id,
        resume_id,
        final_row.get("parse_status", "pending"),
        job_id,
    )
    return SuccessResponse(
        data=UploadResumeResponse(resume=record, parse=parse_info, job_id=job_id)
    )


@router.post(
    "/{resume_id}/parse",
    response_model=SuccessResponse[ParseResumeResponse],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def parse_resume(
    resume_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ParseResumeResponse]:
    """Trigger parsing of an uploaded resume."""
    repo = ResumeRepository(jwt=auth.jwt)
    row = repo.get_resume(auth.user.id, resume_id)
    if not row:
        raise HTTPException(status_code=404, detail="Resume not found")

    storage_path = row.get("storage_path")
    original_filename = row.get("original_filename", "")
    if not storage_path:
        raise HTTPException(status_code=400, detail="No file associated with this resume")

    # Mark as processing
    repo.update_resume(auth.user.id, resume_id, {"parse_status": "processing"})

    # Download file from storage using an RLS-authenticated client.
    storage_client = get_authenticated_client(auth.jwt)
    try:
        file_data = storage_client.storage.from_("resumes").download(storage_path)
    except Exception:
        logger.exception("Failed to download resume file resume_id=%s", resume_id)
        repo.update_resume(auth.user.id, resume_id, {"parse_status": "failed"})
        raise HTTPException(status_code=500, detail="Failed to download file from storage")

    # Reject oversized uploads before loading them into memory / parsing.
    max_bytes = get_settings().max_resume_upload_bytes
    if is_file_too_large(file_data, max_bytes):
        repo.update_resume(auth.user.id, resume_id, {"parse_status": "failed"})
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Resume file exceeds the maximum allowed size of {max_bytes // (1024 * 1024)} MB",
        )

    # Parse
    parser = ResumeParsingService()
    temp_path = f"/tmp/{uuid.uuid4().hex}{Path(original_filename).suffix}"
    try:
        with open(temp_path, "wb") as f:
            f.write(file_data)
        result: ParseResult = await parser.parse_file(temp_path, original_filename)
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass

    version_id = None
    if result.status == "completed":
        content_update = {"content": result.content}
        meta_update = {"meta": {"parse_error": None}}
        repo.update_resume(auth.user.id, resume_id, {**content_update, **meta_update})
        version = repo.create_version(
            resume_id=resume_id,
            content=result.content,
            version_name="v1",
            source="upload_parse",
        )
        version_id = version.get("id")
        repo.update_resume(auth.user.id, resume_id, {"parse_status": "completed"})
    else:
        repo.update_resume(
            auth.user.id,
            resume_id,
            {"parse_status": "failed", "meta": {"parse_error": result.error}},
        )

    return SuccessResponse(
        data=ParseResumeResponse(
            resume_id=resume_id,
            version_id=version_id,
            status=result.status,
            parsed=result.extracted if result.status == "completed" else None,
        )
    )


@router.get(
    "/{resume_id}/completeness",
    response_model=SuccessResponse[CompletenessResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_completeness(
    resume_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[CompletenessResponse]:
    """Calculate resume data completeness."""
    repo = ResumeRepository(jwt=auth.jwt)
    row = repo.get_resume(auth.user.id, resume_id)
    if not row:
        raise HTTPException(status_code=404, detail="Resume not found")

    content = row.get("content") or {}
    profile = content.get("profile", {})
    meta = content.get("meta", {})

    sections: dict[str, dict[str, Any]] = {}
    recommendations: list[str] = []

    # Personal
    personal = profile.get("personal", {})
    personal_complete = any([
        personal.get("full_name"),
        personal.get("email"),
        personal.get("phone"),
    ])
    sections["personal"] = {
        "complete": personal_complete,
        "missing": [k for k in ["full_name", "email", "phone", "location", "linkedin", "github"] if not personal.get(k)],
    }
    if not personal_complete:
        recommendations.append("Add your full name, email, and phone number.")

    # Experience
    experience = profile.get("experience", [])
    sections["experience"] = {
        "complete": len(experience) > 0,
        "count": len(experience),
        "missing": "Add at least one work experience." if not experience else None,
    }
    if not experience:
        recommendations.append("Add your work experience with company, role, and dates.")

    # Education
    education = profile.get("education", [])
    sections["education"] = {
        "complete": len(education) > 0,
        "count": len(education),
        "missing": "Add your education details." if not education else None,
    }
    if not education:
        recommendations.append("Add your education details.")

    # Skills
    skills = profile.get("skills", {})
    has_skills = any([
        skills.get("technical"),
        skills.get("tools"),
        skills.get("languages"),
        skills.get("databases"),
        skills.get("analytics"),
        skills.get("soft_skills"),
    ])
    sections["skills"] = {
        "complete": has_skills,
        "count": sum(len(v) for v in skills.values() if isinstance(v, list)),
        "missing": "Add your skills." if not has_skills else None,
    }
    if not has_skills:
        recommendations.append("Add your technical and soft skills.")

    # Projects
    projects = profile.get("projects", [])
    sections["projects"] = {
        "complete": len(projects) > 0,
        "count": len(projects),
        "missing": None,
    }

    # Certifications
    certifications = profile.get("certifications", [])
    sections["certifications"] = {
        "complete": len(certifications) > 0,
        "count": len(certifications),
        "missing": None,
    }

    # Achievements
    achievements = profile.get("achievements", [])
    sections["achievements"] = {
        "complete": len(achievements) > 0,
        "count": len(achievements),
        "missing": None,
    }

    # Languages
    languages = profile.get("languages", [])
    sections["languages"] = {
        "complete": len(languages) > 0,
        "count": len(languages),
        "missing": None,
    }

    # Links
    links = profile.get("links", [])
    sections["links"] = {
        "complete": len(links) > 0,
        "count": len(links),
        "missing": None,
    }

    # Calculate score
    section_weights = {
        "personal": 20,
        "experience": 25,
        "education": 15,
        "skills": 20,
        "projects": 10,
        "certifications": 5,
        "achievements": 5,
    }
    score = 0.0
    for section, weight in section_weights.items():
        if sections.get(section, {}).get("complete"):
            score += weight

    return SuccessResponse(
        data=CompletenessResponse(
            score=min(score, 100.0),
            sections=sections,
            recommendations=recommendations,
        )
    )