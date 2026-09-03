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
            repo.update_resume(
                user_id,
                resume_id,
                {
                    "content": parse_result.content,
                    "meta": {"parse_error": None},
                    "parse_status": "completed",
                },
            )
            repo.create_version(
                resume_id=resume_id,
                content=parse_result.content,
                version_name="v1",
                source="upload_parse",
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
