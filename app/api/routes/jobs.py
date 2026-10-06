"""Jobs API routes."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.service import AuthContext
from app.dependencies import get_current_user, get_job_relevance_service
from app.repositories.job_intelligence_repository import JobIntelligenceRepository
from app.repositories.job_repository import JobRepository
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.schemas.job import JobOut
from app.services.jobs.job_relevance_service import JobRelevanceService
from app.workers.dispatcher import enqueue

router = APIRouter(prefix="/jobs", tags=["jobs"])

logger = logging.getLogger(__name__)


# ── Fixed-path routes MUST come before /{job_id} parameterized routes ──


@router.get(
    "",
    response_model=SuccessResponse[list[JobOut]],
    responses={400: {"model": ErrorResponse}},
)
async def list_jobs(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    pageSize: Annotated[Optional[int], Query(ge=1, le=100)] = None,
    role: Optional[str] = None,
    location: Optional[str] = None,
    company: Optional[str] = None,
    skills: Optional[str] = None,
    remote: Optional[bool] = None,
    employment_type: Annotated[Optional[str], Query(alias="employmentType")] = None,
    experience: Optional[str] = None,
    sort: Optional[str] = None,
    verified_live_only: Optional[bool] = None,
    service: JobRelevanceService = Depends(get_job_relevance_service),
) -> SuccessResponse[list[JobOut]]:
    """List all active jobs (unauthenticated)."""
    # Frontend sends camelCase pageSize; accept snake_case too.
    page_size = pageSize or page_size
    jobs, total = await asyncio.to_thread(
        service.get_relevant_jobs,
        user_id=None,
        page=page,
        page_size=page_size,
        role=role,
        location=location,
        company=company,
        skills=skills,
        remote=remote,
        employment_type=employment_type,
        experience=experience,
        sort=sort,
    )
    if verified_live_only:
        # Filter for verified live postings (first-party ATS, active)
        first_party_ats = {"ashby", "greenhouse", "lever", "smartrecruiters", "workday"}
        jobs = [j for j in jobs if j.source_platform in first_party_ats and j.source_tier in (1, 2)]
        total = len(jobs)

    return SuccessResponse(
        data=[JobOut.from_db_row(j.model_dump()) for j in jobs],
        meta=build_meta(page, page_size, total),
    )


@router.get(
    "/personalized",
    response_model=SuccessResponse[list[JobOut]],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def list_personalized_jobs(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    pageSize: Annotated[Optional[int], Query(ge=1, le=100)] = None,
    role: Optional[str] = None,
    location: Optional[str] = None,
    company: Optional[str] = None,
    skills: Optional[str] = None,
    remote: Optional[bool] = None,
    employment_type: Annotated[Optional[str], Query(alias="employmentType")] = None,
    experience: Optional[str] = None,
    sort: Optional[str] = None,
    include_ats: Optional[bool] = Query(None),
    includeAts: Optional[bool] = Query(None),
    auth: AuthContext = Depends(get_current_user),
    service: JobRelevanceService = Depends(get_job_relevance_service),
) -> SuccessResponse[list[JobOut]]:
    """List jobs personalized for the authenticated user.

    Note: ``include_ats``/``includeAts`` are accepted for API contract
    compatibility but ATS scoring is not yet implemented in the Python
    backend; ``ats_score`` will remain null until that feature is completed.
    """
    # Frontend sends camelCase pageSize; accept snake_case too.
    page_size = pageSize or page_size
    jobs, total = await asyncio.to_thread(
        service.get_relevant_jobs,
        user_id=auth.user.id,
        page=page,
        page_size=page_size,
        role=role,
        location=location,
        company=company,
        skills=skills,
        remote=remote,
        employment_type=employment_type,
        experience=experience,
        sort=sort,
    )
    return SuccessResponse(
        data=[JobOut.from_db_row(j.model_dump()) for j in jobs],
        meta=build_meta(page, page_size, total),
    )


@router.get(
    "/saved",
    response_model=SuccessResponse[list[dict]],
    responses={401: {"model": ErrorResponse}},
)
async def list_saved_jobs(
    include_ats: Optional[bool] = Query(None),
    includeAts: Optional[bool] = Query(None),
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[list[dict]]:
    """List saved jobs for the authenticated user."""
    res = (
        auth.supabase.table("saved_jobs")
        .select("*, jobs(*)")
        .eq("user_id", auth.user.id)
        .order("created_at", desc=True)
        .execute()
    )
    result = await res if hasattr(res, "__await__") else res
    return SuccessResponse(data=getattr(result, "data", None) or [])


@router.post(
    "/save",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def save_job(
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Save a job for the authenticated user."""
    job_id = body.get("jobId") or body.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="jobId is required")

    res = (
        auth.supabase.table("saved_jobs")
        .upsert({"user_id": auth.user.id, "job_id": job_id}, on_conflict="user_id,job_id")
        .select()
        .execute()
    )
    result = await res if hasattr(res, "__await__") else res
    data = getattr(result, "data", None)
    if isinstance(data, list) and data:
        data = data[0]
    return SuccessResponse(data=data or {"user_id": auth.user.id, "job_id": job_id})


@router.post(
    "/search",
    response_model=SuccessResponse[list[JobOut]],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def search_jobs(
    body: dict,
    auth: AuthContext = Depends(get_current_user),
    service: JobRelevanceService = Depends(get_job_relevance_service),
) -> SuccessResponse[list[JobOut]]:
    """Search jobs with advanced filters."""
    page = int(body.get("page", 1))
    # Accept both camelCase (frontend) and snake_case (API convention).
    page_size = int(body.get("pageSize", body.get("page_size", 20)))
    role = body.get("role")
    location = body.get("location")
    company = body.get("company")
    skills = body.get("skills")
    experience = body.get("experience")
    remote = body.get("remote")
    employment_type = body.get("employmentType") or body.get("employment_type")
    sort = body.get("sort")

    jobs, total = service.get_relevant_jobs(
        user_id=auth.user.id,
        page=page,
        page_size=page_size,
        role=role,
        location=location,
        company=company,
        skills=skills,
        remote=remote,
        employment_type=employment_type,
        experience=experience,
        sort=sort,
    )

    return SuccessResponse(
        data=[JobOut.from_db_row(j.model_dump()) for j in jobs],
        meta=build_meta(page, page_size, total),
    )


@router.post(
    "/match",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def match_job(
    body: dict,
    auth: AuthContext = Depends(get_current_user),
    service: JobRelevanceService = Depends(get_job_relevance_service),
) -> SuccessResponse[dict]:
    """Score a job against the authenticated user's stored profile.

    ``resumeText`` is optional legacy input: scoring uses the stored user
    profile as the source of truth so the Jobs page re-analyze action works
    without the client fabricating resume text. When provided it must still
    be a string; short/empty values simply fall back to the stored profile.
    """
    try:
        resume_text = body.get("resumeText", "")
        if resume_text is not None and not isinstance(resume_text, str):
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_RESUME_TEXT", "message": "resumeText must be a string"},
            )
        job_data = body.get("job") or {}
        if not isinstance(job_data, dict):
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_JOB", "message": "job must be an object"},
            )
        job_id = body.get("jobId") or job_data.get("id") or job_data.get("jobId")
        if not job_id and not job_data:
            raise HTTPException(
                status_code=400,
                detail={"code": "JOB_REQUIRED", "message": "jobId or job is required"},
            )

        try:
            job, match = service.match_job_for_user(
                user_id=auth.user.id,
                job_id=str(job_id) if job_id else None,
                job_data=job_data or None,
                resume_text=resume_text or None,
            )
        except ValueError as exc:
            if str(exc) == "job_not_found":
                raise HTTPException(
                    status_code=404,
                    detail={"code": "JOB_NOT_FOUND", "message": "Job not found"},
                ) from exc
            raise
        return SuccessResponse(data={"job": job.model_dump(), "match": match})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_job_match failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "MATCH_FAILED", "message": "Match failed. Please try again."},
        ) from exc


# ── Parameterized /{job_id} routes below ──


@router.get(
    "/{job_id}",
    response_model=SuccessResponse[JobOut],
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_job(
    job_id: str,
    service: JobRelevanceService = Depends(get_job_relevance_service),
) -> SuccessResponse[JobOut]:
    """Get a single job by id."""
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    job_dict = job.model_dump()
    try:
        from app.services.jobs.job_cluster_service import JobClusterService
        job_dict = JobClusterService().decorate_job_with_cluster_metadata(job_dict)
    except Exception as exc:
        logger.debug("Cluster decoration skipped: %s", exc)

    try:
        from app.services.jobs.ghost_risk_service import GhostRiskService
        grs = GhostRiskService()
        record = grs.get_liveness_record(str(job_dict.get("id") or job_id))
        if record:
            job_dict["ghost_risk"] = {
                "score": record.get("ghost_risk_score", 0),
                "signals": record.get("ghost_signals", []),
                "liveness_status": record.get("liveness_status", "active_unverified"),
            }
            job_dict["is_verified_live"] = record.get("liveness_status") == "verified_live"
        else:
            eval_res = grs.calculate_ghost_risk(job_dict)
            job_dict["ghost_risk"] = eval_res
            job_dict["is_verified_live"] = eval_res.get("is_verified_live", False)
    except Exception as exc:
        logger.debug("Ghost risk decoration skipped: %s", exc)

    return SuccessResponse(data=JobOut.from_db_row(job_dict))


@router.delete(
    "/{job_id}/unsave",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def unsave_job(
    job_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Remove a saved job for the authenticated user."""
    res = auth.supabase.table("saved_jobs").delete().eq("user_id", auth.user.id).eq("job_id", job_id).execute()
    if hasattr(res, "__await__"):
        await res
    return SuccessResponse(data={"unsaved": True})


@router.post(
    "/{job_id}/intelligence/analyze",
    response_model=SuccessResponse[dict],
    responses={404: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def analyze_job_intelligence(
    job_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Queue background extraction of structured intelligence for a job.

    Enqueues the registered ARQ job ``analyze_job_intelligence`` via the
    dispatcher. Returns the ARQ job id so clients can correlate the run.
    """
    job = JobRepository().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    analysis_job_id = await enqueue("analyze_job_intelligence", job_id)
    if analysis_job_id is None:
        raise HTTPException(status_code=503, detail="Failed to queue intelligence analysis")

    return SuccessResponse(
        data={"job_id": job_id, "status": "queued", "analysis_job_id": analysis_job_id}
    )


@router.get(
    "/{job_id}/intelligence",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def get_job_intelligence(
    job_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Return the latest extracted intelligence for a job, if any."""
    intelligence = JobIntelligenceRepository().get_by_job_id(job_id)
    if not intelligence:
        return SuccessResponse(data={"job_id": job_id, "status": "not_analyzed"})
    return SuccessResponse(data=intelligence)

@router.get(
    "/{job_id}/viability",
    response_model=SuccessResponse[dict],
    responses={404: {"model": ErrorResponse}},
)
async def get_job_viability(
    job_id: str,
    auth: AuthContext = Depends(get_current_user),
    service: JobRelevanceService = Depends(get_job_relevance_service),
) -> SuccessResponse[dict]:
    """Calculate and return job viability score (ghost job & high ROI)."""
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    job_out = JobOut.from_db_row(job.model_dump())
    return SuccessResponse(data={
        "is_ghost_job": job_out.is_ghost_job,
        "is_high_roi": job_out.is_high_roi,
        "viability_score": job_out.viability_score,
    })

@router.post(
    "/{job_id}/apply",
    response_model=SuccessResponse[dict],
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def apply_to_job(
    job_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Track a real job as an application (Job → Application bridge).

    Verifies the job exists, prevents accidental duplicates, populates job
    metadata (title, company, location, salary, source URL, match score) and
    returns the persisted application — now visible in Mission Control.
    """
    from app.services.applications import ApplicationService

    job = JobRepository().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    service = ApplicationService()
    app = await service.create_from_job(auth, job)
    if app.get("duplicate"):
        raise HTTPException(
            status_code=409,
            detail="This job is already tracked as an application",
        )
    return SuccessResponse(data=app, status_code=201)
