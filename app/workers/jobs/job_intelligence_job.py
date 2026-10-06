"""ARQ background job for job intelligence analysis."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository
from app.repositories.job_intelligence_repository import JobIntelligenceRepository
from app.services.jobs.job_intelligence_service import JobIntelligenceService
from app.workers.logging import JobLogger
from app.workers.registry import WorkloadClass, register_job

logger = logging.getLogger(__name__)


@register_job(
    "analyze_job_intelligence",
    timeout=120,
    max_tries=2,
    retry=True,
    description="Analyze a job and extract structured intelligence.",
    workload_class=WorkloadClass.ANALYSIS,
)
async def analyze_job_intelligence_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Analyze a job and persist structured intelligence.

    Payload:
        {
            "job_id": "<uuid>"
        }
    """
    job_start = time.monotonic()
    now_ms = int(time.time() * 1000)

    score = ctx.get("score")
    queue_delay_ms = (
        int(now_ms - score)
        if isinstance(score, (int, float))
        else None
    )
    job_try = int(ctx.get("job_try", 1))
    analysis_job_id = str(ctx.get("job_id", "unknown"))

    job_logger = JobLogger(
        job_id=analysis_job_id,
        job_type="job_intelligence",
        source_job_id=job_id,
        job_try=job_try,
        queue_delay_ms=queue_delay_ms if queue_delay_ms is not None else "unknown",
    )

    job_logger.started()

    job_repo = JobRepository()
    intelligence_repo = JobIntelligenceRepository()
    service = JobIntelligenceService()

    job_row = job_repo.get_job(job_id)
    if not job_row:
        duration_ms = int((time.monotonic() - job_start) * 1000)
        cause = job_repo.diagnose_job_missing(job_id)
        logger.info(
            "JOB job_id=%s job_type=job_intelligence status=job_not_found cause=%s duration_ms=%d queue_delay_ms=%s job_try=%d source_job_id=%s",
            analysis_job_id,
            cause,
            duration_ms,
            str(queue_delay_ms or "unknown"),
            job_try,
            job_id,
        )
        return {
            "success": False,
            "job_id": job_id,
            "status": "job_not_found",
            "cause": cause,
            "error": f"job not found ({cause})",
            "duration_ms": duration_ms,
            "queue_delay_ms": queue_delay_ms,
            "job_try": job_try,
        }

    canonical_job_id = str(job_row.get("id") or job_id)
    job = NormalizedJob(**job_row)
    try:
        intelligence = service.analyze_job(job, job_id=canonical_job_id)
    except Exception as exc:
        duration_ms = int((time.monotonic() - job_start) * 1000)
        job_logger.failed(duration_ms=duration_ms, error_type=exc.__class__.__name__, result="failed")
        raise

    intelligence_repo.upsert(intelligence)

    duration_ms = int((time.monotonic() - job_start) * 1000)
    job_logger.completed(
        duration_ms=duration_ms,
        result="completed",
        skills_count=len(intelligence.skills),
        requirements_count=len(intelligence.requirements),
        keywords_count=len(intelligence.keywords),
    )

    return {
        "success": True,
        "job_id": canonical_job_id,
        "skills": len(intelligence.skills),
        "requirements": len(intelligence.requirements),
        "keywords": len(intelligence.keywords),
        "duration_ms": duration_ms,
        "queue_delay_ms": queue_delay_ms,
        "job_try": job_try,
    }


@register_job(
    "analyze_jobs_batch",
    timeout=300,
    max_tries=2,
    retry=True,
    description="Analyze a batch of jobs for structured intelligence in chunks.",
    workload_class=WorkloadClass.ANALYSIS,
)
async def analyze_jobs_batch(ctx: dict[str, Any], job_ids: list[str]) -> dict[str, Any]:
    """Analyze a batch of jobs in chunks to prevent queue backlog."""
    batch_start = time.monotonic()
    now_ms = int(time.time() * 1000)

    score = ctx.get("score")
    queue_delay_ms = (
        int(now_ms - score)
        if isinstance(score, (int, float))
        else None
    )
    job_try = int(ctx.get("job_try", 1))
    batch_job_id = str(ctx.get("job_id", "unknown"))

    job_logger = JobLogger(
        job_id=batch_job_id,
        job_type="job_intelligence_batch",
        batch_size=len(job_ids),
        job_try=job_try,
        queue_delay_ms=queue_delay_ms if queue_delay_ms is not None else "unknown",
    )
    job_logger.started()

    job_repo = JobRepository()
    intelligence_repo = JobIntelligenceRepository()
    service = JobIntelligenceService()

    succeeded = 0
    not_found = 0
    causes: dict[str, int] = {}

    for jid in job_ids:
        job_row = job_repo.get_job(jid)
        if not job_row:
            not_found += 1
            cause = job_repo.diagnose_job_missing(jid)
            causes[cause] = causes.get(cause, 0) + 1
            logger.info(
                "BATCH_JOB_ITEM batch_id=%s source_job_id=%s status=job_not_found cause=%s",
                batch_job_id,
                jid,
                cause,
            )
            continue

        canonical_id = str(job_row.get("id") or jid)
        job = NormalizedJob(**job_row)
        try:
            intelligence = service.analyze_job(job, job_id=canonical_id)
            intelligence_repo.upsert(intelligence)
            succeeded += 1
        except Exception as exc:
            logger.warning(
                "Job intelligence analysis item failed for %s (%s)",
                canonical_id,
                type(exc).__name__,
            )

    duration_ms = int((time.monotonic() - batch_start) * 1000)
    job_logger.completed(
        duration_ms=duration_ms,
        result="completed",
        total=len(job_ids),
        succeeded=succeeded,
        not_found=not_found,
    )

    return {
        "success": True,
        "batch_id": batch_job_id,
        "total": len(job_ids),
        "succeeded": succeeded,
        "not_found": not_found,
        "causes": causes,
        "duration_ms": duration_ms,
        "queue_delay_ms": queue_delay_ms,
        "job_try": job_try,
    }

