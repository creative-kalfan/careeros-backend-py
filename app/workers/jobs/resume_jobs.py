"""ARQ background job for resume parsing."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from app.db.supabase import get_service_client
from app.repositories.resume_repository import ResumeRepository
from app.services.resume_parsing import ParseResult, ResumeParsingService, is_file_too_large

logger = logging.getLogger(__name__)


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
    """
    if not resume_id or not user_id or not storage_path:
        raise ValueError("Missing required job fields: resume_id, user_id, storage_path")

    repo = ResumeRepository()

    row = repo.get_resume(user_id, resume_id)
    if not row:
        raise ValueError(f"Resume {resume_id} not found for user {user_id}")

    if row.get("parse_status") == "completed":
        logger.info("PARSE JOB SKIP resume_id=%s already completed", resume_id)
        return {"success": True, "resume_id": resume_id, "status": "completed", "skipped": True}

    repo.update_resume(user_id, resume_id, {"parse_status": "processing"})
    logger.info(
        "PARSE JOB START resume_id=%s user_id=%s storage_path=%s",
        resume_id,
        user_id,
        storage_path,
    )

    storage_client = get_service_client()
    try:
        file_data = await asyncio.to_thread(
            storage_client.storage.from_("resumes").download, storage_path
        )
    except Exception as exc:
        logger.error("PARSE JOB DOWNLOAD FAILED resume_id=%s error=%s", resume_id, exc)
        repo.update_resume(
            user_id,
            resume_id,
            {
                "parse_status": "failed",
                "meta": {"parse_error": "Failed to download file from storage"},
            },
        )
        raise

    # Reject oversized uploads before writing to disk / parsing.
    if is_file_too_large(file_data):
        logger.info("PARSE JOB FILE TOO LARGE resume_id=%s", resume_id)
        repo.update_resume(
            user_id,
            resume_id,
            {
                "parse_status": "failed",
                "meta": {"parse_error": "Resume file exceeds the maximum allowed upload size"},
            },
        )
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
            logger.info("PARSE JOB COMPLETED resume_id=%s", resume_id)
        else:
            repo.update_resume(
                user_id,
                resume_id,
                {
                    "parse_status": "failed",
                    "meta": {"parse_error": parse_result.error or "Parsing failed"},
                },
            )
            logger.info(
                "PARSE JOB FAILED resume_id=%s error=%s",
                resume_id,
                parse_result.error,
            )

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
