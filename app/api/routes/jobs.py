"""Jobs API routes."""

from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.service import AuthContext
from app.dependencies import get_current_user, get_job_relevance_service
from app.models.job import NormalizedJob
from app.models.profile import UserProfile
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
    role: Optional[str] = None,
    location: Optional[str] = None,
    company: Optional[str] = None,
    skills: Optional[str] = None,
    remote: Optional[bool] = None,
    employment_type: Annotated[Optional[str], Query(alias="employmentType")] = None,
    experience: Optional[str] = None,
    sort: Optional[str] = None,
    service: JobRelevanceService = Depends(get_job_relevance_service),
) -> SuccessResponse[list[JobOut]]:
    """List all active jobs (unauthenticated)."""
    jobs, total = service.get_relevant_jobs(
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
    role: Optional[str] = None,
    location: Optional[str] = None,
    company: Optional[str] = None,
    skills: Optional[str] = None,
    remote: Optional[bool] = None,
    employment_type: Annotated[Optional[str], Query(alias="employmentType")] = None,
    experience: Optional[str] = None,
    sort: Optional[str] = None,
    include_ats: Optional[bool] = Query(None),
    auth: AuthContext = Depends(get_current_user),
    service: JobRelevanceService = Depends(get_job_relevance_service),
) -> SuccessResponse[list[JobOut]]:
    """List jobs personalized for the authenticated user.

    Note: ``include_ats`` is accepted for API contract compatibility but ATS
    scoring is not yet implemented in the Python backend; ``ats_score`` will
    remain null until that feature is completed.
    """
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


@router.get(
    "/saved",
    response_model=SuccessResponse[list[dict]],
    responses={401: {"model": ErrorResponse}},
)
async def list_saved_jobs(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[list[dict]]:
    """List saved jobs for the authenticated user."""
    result = (
        auth.supabase.table("saved_jobs")
        .select("*, jobs(*)")
        .eq("user_id", auth.user.id)
        .order("created_at", desc=True)
        .execute()
    )
    return SuccessResponse(data=result.data or [])


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
    job_id = body.get("jobId")
    if not job_id:
        raise HTTPException(status_code=400, detail="jobId is required")

    result = (
        auth.supabase.table("saved_jobs")
        .upsert({"user_id": auth.user.id, "job_id": job_id}, onConflict="user_id,job_id")
        .select()
        .single()
        .execute()
    )
    return SuccessResponse(data=result.data or {})


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
    page_size = int(body.get("pageSize", 20))
    role = body.get("role")
    location = body.get("location")
    company = body.get("company")
    skills = body.get("skills")
    experience = body.get("experience")
    remote = body.get("remote")
    employment_type = body.get("employmentType")
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
) -> SuccessResponse[dict]:
    """Match a resume against a job description."""
    try:
        resume_text = body.get("resumeText", "")
        job_data = body.get("job", {})

        if not resume_text or not isinstance(resume_text, str) or len(resume_text) < 20:
            raise HTTPException(status_code=400, detail="resumeText must be a non-empty string")

        from app.services.jobs.job_relevance_service import JobRelevanceService

        service = JobRelevanceService()
        job = None
        try:
            job = service.get_job(job_data.get("id", ""))
        except Exception:
            job = None
        if not job:
            job = NormalizedJob.model_validate(job_data)

        match = service.personalized_service.calculate_match_score(
            job,
            UserProfile(
                id=None,
                current_role=None,
                desired_role=None,
                skills=[],
                location=None,
                preferred_locations=[],
                remote_preference="any",
                preferred_companies=[],
                salary_expectation_min=None,
                salary_expectation_max=None,
                salary_currency=None,
                experience=None,
                education=[],
                onboarding_completed=False,
                onboarding_step=0,
            ),
        )
        return SuccessResponse(data={"job": job.model_dump(), "match": match})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_job_match failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Match failed. Please try again.",
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
    return SuccessResponse(data=JobOut.from_db_row(job.model_dump()))


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
    auth.supabase.table("saved_jobs").delete().eq("user_id", auth.user.id).eq("job_id", job_id).execute()
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
