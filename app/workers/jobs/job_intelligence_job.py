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
from app.workers.registry import register_job

logger = logging.getLogger(__name__)


@register_job(
    "analyze_job_intelligence",
    timeout=120,
    max_tries=2,
    retry=True,
    description="Analyze a job and extract structured intelligence.",
)
async def analyze_job_intelligence_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Analyze a job and persist structured intelligence.

    Payload:
        {
            "job_id": "<uuid>"
        }
    """
    job_logger = JobLogger(job_id=ctx.get("job_id", "unknown"), job_type="job_intelligence", source_job_id=job_id)
    job_start = time.monotonic()

    job_logger.started()

    repo = JobRepository()
    job_repo = JobRepository()
    intelligence_repo = JobIntelligenceRepository()
    service = JobIntelligenceService()

    job_row = job_repo.get_job(job_id)
    if not job_row:
        duration_ms = int((time.monotonic() - job_start) * 1000)
        job_logger.failed(duration_ms=duration_ms, error_type="JobNotFound")
        return {"success": False, "job_id": job_id, "error": "job not found"}

    job = NormalizedJob(**job_row)
    try:
        intelligence = service.analyze_job(job, job_id=job_id)
    except Exception as exc:
        duration_ms = int((time.monotonic() - job_start) * 1000)
        job_logger.failed(duration_ms=duration_ms, error_type=exc.__class__.__name__)
        raise

    intelligence_repo.upsert(intelligence)

    duration_ms = int((time.monotonic() - job_start) * 1000)
    job_logger.completed(
        duration_ms=duration_ms,
        skills_count=len(intelligence.skills),
        requirements_count=len(intelligence.requirements),
        keywords_count=len(intelligence.keywords),
    )

    return {
        "success": True,
        "job_id": job_id,
        "skills": len(intelligence.skills),
        "requirements": len(intelligence.requirements),
        "keywords": len(intelligence.keywords),
        "duration_ms": duration_ms,
    }
