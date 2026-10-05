"""Worker functions for CareerOS ARQ queue."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from arq.worker import Retry

from app.db.supabase import get_service_client
from app.repositories.resume_repository import ResumeRepository
from app.services.resume_parsing import (
    ParseResult,
    ResumeParsingService,
    is_file_too_large,
)
from app.workers.logging import JobLogger
from app.workers.registry import register_job


logger = logging.getLogger(__name__)

if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s: %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


@register_job(
    "discover_ats_targets",
    timeout=180,
    max_tries=2,
    retry=True,
    description="Discover and verify a bounded daily batch of ATS boards.",
)
async def discover_ats_targets_job(ctx: dict[str, Any]) -> dict[str, int]:
    from app.services.jobs.source_discovery import discover_ats_targets

    return await discover_ats_targets(ctx)


@register_job(
    "careeros_worker_health",
    timeout=60,
    max_tries=1,
    retry=False,
    description="Minimal health check job to verify the ARQ pipeline is functional.",
)
async def careeros_worker_health(ctx: dict[str, Any]) -> dict[str, str]:
    """Minimal health check job to verify the ARQ pipeline is functional."""
    return {
        "status": "ok",
        "message": "CareerOS ARQ worker is alive",
    }


@register_job(
    "parse_resume_job",
    timeout=120,
    max_tries=2,
    retry=True,
    description="Parse an uploaded resume in the background.",
)
async def parse_resume_job(
    ctx: dict[str, Any],
    resume_id: str,
    user_id: str,
    storage_path: str,
) -> dict[str, Any]:
    """Parse an uploaded resume in the background.

    Job payload (validated by the register endpoint before enqueue):
        {
            "resume_id": "<UUID>",
            "user_id": "<UUID>",
            "storage_path": "<user_id>/<uuid>.pdf"
        }

    Lifecycle:
        pending -> processing -> completed
        pending -> processing -> failed

    Idempotency:
        If the resume is already completed, the job returns early without
        re-parsing or creating duplicate versions.
    """
    job_id: str = ctx.get("job_id", "unknown")
    job_logger = JobLogger(job_id=job_id, job_type="parse_resume", resume_id=resume_id)
    job_start = time.monotonic()

    job_logger.started()

    if not resume_id or not user_id or not storage_path:
        raise ValueError("Missing required job fields: resume_id, user_id, storage_path")

    repo = ResumeRepository()

    row = repo.get_resume(user_id, resume_id)
    if not row:
        raise ValueError(f"Resume {resume_id} not found for user {user_id}")

    if row.get("parse_status") == "completed":
        job_logger.processing(reason="already_completed")
        return {"success": True, "resume_id": resume_id, "status": "completed", "skipped": True}

    repo.update_resume(user_id, resume_id, {"parse_status": "processing"})
    job_logger.processing()

    storage_client = get_service_client()
    try:
        file_data = await asyncio.to_thread(
            storage_client.storage.from_("resumes").download, storage_path
        )
    except Exception as exc:
        error_name = exc.__class__.__name__
        status_code = None
        if hasattr(exc, "status_code"):
            status_code = exc.status_code
        elif hasattr(exc, "statusCode"):
            status_code = exc.statusCode
        elif exc.args and isinstance(exc.args[0], dict):
            status_code = exc.args[0].get("statusCode")
        elif exc.args and isinstance(exc.args[0], str):
            match = re.search(r"'statusCode':\s*(\d+)", exc.args[0])
            if match:
                status_code = int(match.group(1))
        duration_ms = int((time.monotonic() - job_start) * 1000)
        job_logger.failed(duration_ms=duration_ms, error_type=error_name, status_code=status_code)
        repo.update_resume(
            user_id,
            resume_id,
            {
                "parse_status": "failed",
                "meta": {"parse_error": "Failed to download file from storage"},
            },
        )
        if error_name in ("ConnectionError", "TimeoutError", "RedisError"):
            raise Retry(defer=30) from exc
        if error_name == "StorageApiError" and status_code and status_code >= 500:
            raise Retry(defer=30) from exc
        raise

    # Reject oversized uploads before writing to disk / parsing.
    if is_file_too_large(file_data):
        logger.warning("PARSE JOB FILE TOO LARGE resume_id=%s", resume_id)
        repo.update_resume(
            user_id,
            resume_id,
            {
                "parse_status": "failed",
                "meta": {"parse_error": "Resume file exceeds the maximum allowed upload size"},
            },
        )
        duration_ms = int((time.monotonic() - job_start) * 1000)
        job_logger.failed(duration_ms=duration_ms, error_type="FileTooLarge")
        return {
            "success": False,
            "resume_id": resume_id,
            "status": "failed",
            "skipped": True,
            "error": "file_too_large",
        }

    parser = ResumeParsingService()
    filename = Path(storage_path).name
    temp_path = f"/tmp/{uuid.uuid4().hex}{Path(storage_path).suffix}"
    try:
        with open(temp_path, "wb") as f:
            f.write(file_data)

        parse_result: ParseResult = await parser.parse_file(temp_path, filename)

        if parse_result.status == "completed":
            meta_payload: dict[str, Any] = {"parse_error": None}
            if parse_result.geometry:
                meta_payload["geometry"] = parse_result.geometry

            repo.update_resume(
                user_id,
                resume_id,
                {
                    "content": parse_result.content,
                    "meta": meta_payload,
                    "parse_status": "completed",
                },
            )
            v1_meta: dict[str, Any] = {}
            if storage_path:
                v1_meta["storage_path"] = storage_path
            if parse_result.geometry:
                v1_meta["geometry"] = parse_result.geometry
            repo.create_version(
                resume_id=resume_id,
                content=parse_result.content,
                version_name="v1",
                source="upload_parse",
                is_master=True,
                meta=v1_meta,
            )
            duration_ms = int((time.monotonic() - job_start) * 1000)
            job_logger.completed(duration_ms=duration_ms, status="completed")
        else:
            repo.update_resume(
                user_id,
                resume_id,
                {
                    "parse_status": "failed",
                    "meta": {"parse_error": parse_result.error or "Parsing failed"},
                },
            )
            duration_ms = int((time.monotonic() - job_start) * 1000)
            job_logger.failed(duration_ms=duration_ms, error_type="ParseError", error=parse_result.error)

        return {
            "success": parse_result.status == "completed",
            "resume_id": resume_id,
            "status": parse_result.status,
        }
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass

@register_job(
    "aggregate_market_skill_trends_job",
    timeout=60,
    max_tries=1,
    retry=False,
    description="Cron/ARQ task to aggregate active job skills by role_title.",
)
async def aggregate_market_skill_trends_job(ctx: dict[str, Any]) -> dict[str, str]:
    """Cron/ARQ task to aggregate active job skills by role_title."""
    from app.db.supabase import get_service_client
    import logging

    logger = logging.getLogger(__name__)
    supabase = get_service_client()
    try:
        res = supabase.rpc("aggregate_skill_trends", {}).execute()
        return {"status": "success", "message": "Aggregated market skill trends"}
    except Exception as e:
        logger.exception("Failed to aggregate market skill trends")
        return {"status": "error", "message": str(e)}


@register_job(
    "scan_and_alert_high_roi_jobs",
    timeout=120,
    max_tries=2,
    retry=True,
    description="Scan newly ingested jobs with is_high_roi=True and send WhatsApp alerts to matching users.",
)
async def scan_and_alert_high_roi_jobs(ctx: dict[str, Any], job_ids: list[str] | None = None) -> dict[str, Any]:
    """If a job is ingested that matches a user's target role and has is_high_roi = True,

    send a WhatsApp message: "New [Role] role at [Company]. Reply 'TAILOR' to generate a custom resume."
    """
    from app.db.supabase import get_service_client
    from app.utils.whatsapp import send_whatsapp_message
    from app.workers.settings import get_redis_pool

    supabase = get_service_client()
    alerts_sent = 0

    try:
        query = supabase.table("jobs").select("id, title, company, role_category, is_high_roi").eq("is_high_roi", True).eq("is_active", True)
        if job_ids:
            query = query.in_("id", job_ids)
        else:
            query = query.order("created_at", desc=True).limit(20)

        res = query.execute()
        high_roi_jobs = res.data or []
        if not high_roi_jobs:
            return {"status": "ok", "alerts_sent": 0, "message": "No high ROI jobs found."}

        # Query users with phone numbers and target roles
        profiles_res = supabase.table("profiles").select("id, phone, target_role, user_id").execute()
        profiles = [p for p in (profiles_res.data or []) if p.get("phone")]

        redis = await get_redis_pool()

        for job in high_roi_jobs:
            role = job.get("title") or "Engineering"
            company = job.get("company") or "Tech Corp"
            job_id = job.get("id")

            for prof in profiles:
                phone = prof.get("phone")
                user_target = (prof.get("target_role") or "").lower()
                user_id = prof.get("user_id") or prof.get("id")

                # Match role
                if user_target and (user_target in role.lower() or role.lower() in user_target or "software" in role.lower()):
                    # Avoid spamming duplicate alerts for same job to same phone
                    cache_key = f"whatsapp_alert_sent:{phone}:{job_id}"
                    already_sent = await redis.get(cache_key)
                    if already_sent:
                        continue

                    msg = f"New {role} role at {company}. Reply 'TAILOR' to generate a custom resume."
                    sent = await send_whatsapp_message(phone, msg)
                    if sent:
                        alerts_sent += 1
                        # Save state in redis so webhook knows which job and user to tailor for
                        clean_num = phone.replace("whatsapp:", "").strip()
                        await redis.setex(f"pending_tailor_job:{clean_num}", 86400 * 2, f"{user_id}:{job_id}")
                        await redis.setex(cache_key, 86400 * 7, "1")

        return {"status": "ok", "alerts_sent": alerts_sent}
    except Exception as exc:
        logger.exception("Failed scan_and_alert_high_roi_jobs: %s", exc)
        return {"status": "error", "error": str(exc), "alerts_sent": alerts_sent}

