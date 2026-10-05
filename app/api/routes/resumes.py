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
    TailorRequest,
    TranslateProjectRequest,
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
resume_singular_router = APIRouter(prefix="/api/resume", tags=["resume"])

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
    import tempfile
    parser = ResumeParsingService()
    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, f"{uuid.uuid4().hex}{Path(original_filename).suffix}")
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
        meta_payload: dict[str, Any] = {"parse_error": None}
        if result.geometry:
            meta_payload["geometry"] = result.geometry
        meta_update = {"meta": meta_payload}
        repo.update_resume(auth.user.id, resume_id, {**content_update, **meta_update})
        v1_meta: dict[str, Any] = {}
        if storage_path:
            v1_meta["storage_path"] = storage_path
        if result.geometry:
            v1_meta["geometry"] = result.geometry
        existing_master = repo.get_master_version(resume_id)
        if existing_master:
            version = repo.update_version(
                existing_master["id"],
                {"content": result.content, "meta": {**existing_master.get("meta", {}), **v1_meta}},
            )
        else:
            version = repo.create_version(
                resume_id=resume_id,
                content=result.content,
                version_name="v1",
                source="upload_parse",
                is_master=True,
                meta=v1_meta,
            )
        version_id = version.get("id") if version else None
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

@router.post(
    "/tailor",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
@resume_singular_router.post(
    "/tailor",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def tailor_resume_for_job(
    body: TailorRequest,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """1-Click Auto-Tailor: Tailor a resume to a specific job."""
    from app.repositories.resume_repository import ResumeRepository
    from app.repositories.job_repository import JobRepository
    from app.services.optimization.whole_resume_tailoring_service import WholeResumeTailoringService
    from app.models.resume import ResumeContent

    # Fetch Job
    job = JobRepository().get_job(body.job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    
    # Fetch Resume
    resume_repo = ResumeRepository(auth.supabase)
    resume = resume_repo.get_resume(auth.user.id, body.resume_id)
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found",
        )
    
    content_dict = resume.get("content") or {}
    # Convert dict to ResumeContent model
    try:
        resume_content = ResumeContent.model_validate(content_dict)
    except Exception as e:
        logger.error(f"Failed to parse resume content: {e}")
        raise HTTPException(status_code=400, detail="Invalid resume content")
    
    job_description = job.get("description") or ""
    job_title = job.get("title") or ""
    company = job.get("company") or ""

    if not job_description:
        raise HTTPException(status_code=400, detail="Job has no description to tailor against")

    try:
        service = WholeResumeTailoringService()
        tailor_result = service.tailor_resume(
            resume_content=resume_content,
            job_description=job_description,
            job_title=job_title,
            company=company,
        )
        
        return SuccessResponse(
            data={
                "success": tailor_result.success,
                "plan": [p.model_dump() for p in tailor_result.plan],
                "tailored_profile": tailor_result.tailored_profile,
                "score_comparison": tailor_result.score_comparison.model_dump(),
                "message": tailor_result.message,
                "limited_alignment": tailor_result.limited_alignment,
                "alignment_message": tailor_result.alignment_message,
            }
        )
    except Exception as e:
        logger.exception("Auto-tailoring failed")
        raise HTTPException(status_code=500, detail="Failed to tailor resume")


@router.post("/translate-project", response_model=SuccessResponse[dict[str, Any]])
@resume_singular_router.post("/translate-project", response_model=SuccessResponse[dict[str, Any]])
async def translate_project(
    body: TranslateProjectRequest,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict[str, Any]]:
    """Convert raw personal project details into an ATS-optimized ExperienceNode AST node."""
    return await _handle_translate_project(body, auth)


async def _handle_translate_project(
    body: TranslateProjectRequest,
    auth: AuthContext,
) -> SuccessResponse[dict[str, Any]]:
    import json
    from app.llm import get_llm_gateway
    from app.llm.types import LLMRequest, LLMTask, LLMProvider
    from app.models.resume_ast import ExperienceNode

    # 1. Query market_skill_trends for the target role
    trends_skills: list[str] = []
    try:
        res = (
            auth.supabase.table("market_skill_trends")
            .select("skill_name")
            .eq("role_title", body.role_title)
            .order("frequency", desc=True)
            .limit(15)
            .execute()
        )
        data = res.data or []
        trends_skills = [d.get("skill_name") for d in data if d.get("skill_name")]
    except Exception as exc:
        logger.warning("Error fetching market_skill_trends: %s", exc)

    if not trends_skills:
        try:
            res_gen = (
                auth.supabase.table("market_skill_trends")
                .select("skill_name")
                .eq("role_title", "General")
                .order("frequency", desc=True)
                .limit(10)
                .execute()
            )
            data_gen = res_gen.data or []
            trends_skills = [d.get("skill_name") for d in data_gen if d.get("skill_name")]
        except Exception:
            pass

    skills_context = ", ".join(trends_skills) if trends_skills else "Python, FastAPI, SQL, Docker, React, Git"

    # 2. Construct LLM prompt for Groq to output typed ExperienceNode AST
    prompt = (
        f"You are an expert ATS Resume and Career Architect.\n"
        f"Convert the following raw project details into an ATS-optimized work experience node for the target role: '{body.role_title}'.\n"
        f"Highlight and prioritize the following high-demand market skills where applicable: {skills_context}.\n\n"
        f"Raw Project Details:\n\"\"\"{body.project_details}\"\"\"\n\n"
        f"Respond ONLY with a valid JSON object matching this exact schema (no markdown, no extra commentary):\n"
        f"{{\n"
        f'  "type": "experience",\n'
        f'  "company": "Project / Freelance (or deduced organization/project name)",\n'
        f'  "role": "{body.role_title}",\n'
        f'  "description": "Short 1-2 sentence overview of the project impact and tech architecture",\n'
        f'  "start_date": "YYYY-MM or null",\n'
        f'  "end_date": "Present or YYYY-MM or null",\n'
        f'  "bullets": [\n'
        f'    "Action verb + engineered achievement + high-demand tech metric",\n'
        f'    "Quantified outcome using market-aligned skills"\n'
        f"  ]\n"
        f"}}"
    )

    llm = get_llm_gateway()
    try:
        response = await llm.generate(
            LLMRequest(
                task=LLMTask.RESUME_SECTION_SUGGESTION,
                prompt=prompt,
                system_instruction="You are a strict JSON generator for ATS resume AST structures. Output raw JSON only.",
                provider=LLMProvider.GROQ,
                temperature=0.2,
            )
        )
        content = response.content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        parsed = json.loads(content)
        parsed["type"] = "experience"
        # Validate against ExperienceNode
        node = ExperienceNode.model_validate(parsed)
        return SuccessResponse(data=node.model_dump(mode="json"))
    except Exception as exc:
        logger.exception("Failed to translate project into ExperienceNode AST: %s", exc)
        # Deterministic fallback ExperienceNode
        fallback_node = ExperienceNode(
            company="Project",
            role=body.role_title,
            description=f"Developed technical project focused on {body.role_title} requirements.",
            bullets=[
                f"Implemented core project features focusing on {skills_context.split(',')[0].strip()}.",
                f"Delivered production-ready implementation adhering to best engineering practices.",
            ],
        )
        return SuccessResponse(data=fallback_node.model_dump(mode="json"))