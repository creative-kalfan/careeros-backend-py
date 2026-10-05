"""WhatsApp Webhook API router.

Handles incoming webhook events from Twilio and Meta WhatsApp API.
Specifically listens for 'TAILOR' replies to asynchronously trigger resume
tailoring and reply with tailored draft link.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
from fastapi import APIRouter, Request, Response, BackgroundTasks
from pydantic import BaseModel

from app.db.supabase import get_service_client
from app.models.resume import ResumeContent
from app.repositories.job_repository import JobRepository
from app.repositories.resume_repository import ResumeRepository
from app.services.optimization.whole_resume_tailoring_service import WholeResumeTailoringService
from app.utils.whatsapp import send_whatsapp_message
from app.workers.settings import get_redis_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/whatsapp", tags=["webhooks"])


async def process_whatsapp_tailor(sender_phone: str, user_id: str, job_id: str) -> None:
    """Asynchronously execute resume tailoring and send WhatsApp reply."""
    supabase = get_service_client()
    try:
        # 1. Fetch Job
        job = JobRepository().get_job(job_id)
        if not job:
            await send_whatsapp_message(sender_phone, "Sorry, we could not find the target job listing to tailor against.")
            return

        job_title = job.get("title") or "Software Engineer"
        company = job.get("company") or "the company"
        job_desc = job.get("description") or ""

        # 2. Fetch User Master Resume
        resume_repo = ResumeRepository(supabase)
        resumes = resume_repo.list_resumes(user_id)
        if not resumes:
            await send_whatsapp_message(sender_phone, "No resume found in your CareerOS profile. Please upload a resume first.")
            return

        resume = resumes[0]
        resume_id = resume.get("id")
        content_dict = resume.get("content") or {}
        resume_content = ResumeContent.model_validate(content_dict)

        # 3. Execute whole resume tailoring
        service = WholeResumeTailoringService()
        tailor_result = await asyncio.to_thread(
            service.tailor_resume,
            resume_content=resume_content,
            job_description=job_desc,
            job_title=job_title,
            company=company,
        )

        # 4. Save tailored version
        version = resume_repo.create_version(
            resume_id=resume_id,
            content={"profile": tailor_result.tailored_profile},
            version_name=f"Tailored for {company} ({job_title})",
            source="manual",
            is_master=False,
            meta={"tailored_job_id": job_id, "score_comparison": tailor_result.score_comparison.model_dump()},
        )
        version_id = version.get("id") if isinstance(version, dict) else "latest"

        # 5. Send success reply with draft link
        draft_url = f"https://careeros.app/resumes/{resume_id}?versionId={version_id}"
        reply_text = (
            f"Success! Your resume has been tailored for {job_title} at {company}.\n"
            f"View your tailored draft here: {draft_url}"
        )
        await send_whatsapp_message(sender_phone, reply_text)

    except Exception as exc:
        logger.exception("Error in process_whatsapp_tailor for %s: %s", sender_phone, exc)
        await send_whatsapp_message(sender_phone, "There was an issue tailoring your resume. Please check your CareerOS dashboard.")


@router.post("")
@router.post("/")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
    """Handle incoming WhatsApp messages from Twilio or Meta webhook."""
    sender_phone = ""
    incoming_body = ""

    # Check content type
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type:
        form_data = await request.form()
        sender_phone = str(form_data.get("From") or "")
        incoming_body = str(form_data.get("Body") or "")
    else:
        try:
            body_json = await request.json()
            # Meta WhatsApp payload format
            entry = (body_json.get("entry") or [{}])[0]
            changes = (entry.get("changes") or [{}])[0]
            value = changes.get("value") or {}
            messages = value.get("messages") or []
            if messages:
                msg = messages[0]
                sender_phone = msg.get("from") or ""
                incoming_body = (msg.get("text") or {}).get("body") or ""
        except Exception:
            pass

    incoming_text = incoming_body.strip().upper()
    logger.info("Received WhatsApp webhook from '%s': '%s'", sender_phone, incoming_text)

    if "TAILOR" in incoming_text and sender_phone:
        clean_num = sender_phone.replace("whatsapp:", "").replace("+", "").strip()
        try:
            redis = await get_redis_pool()
            # Retrieve pending tailor job
            pending = await redis.get(f"pending_tailor_job:{clean_num}")
            if not pending:
                # Also try looking up with '+'
                pending = await redis.get(f"pending_tailor_job:+{clean_num}")

            if pending:
                if isinstance(pending, bytes):
                    pending = pending.decode("utf-8")
                user_id, _, job_id = pending.partition(":")
                background_tasks.add_task(process_whatsapp_tailor, sender_phone, user_id, job_id)
            else:
                # Try finding user by phone in DB
                supabase = get_service_client()
                prof_res = (
                    supabase.table("profiles")
                    .select("id, user_id")
                    .or_(f"phone.eq.{clean_num},phone.eq.+{clean_num}")
                    .limit(1)
                    .execute()
                )
                profiles = prof_res.data or []
                if profiles:
                    uid = profiles[0].get("user_id") or profiles[0].get("id")
                    # Find recent high ROI job
                    job_res = supabase.table("jobs").select("id").eq("is_high_roi", True).eq("is_active", True).limit(1).execute()
                    jobs = job_res.data or []
                    if jobs:
                        background_tasks.add_task(process_whatsapp_tailor, sender_phone, uid, jobs[0].get("id"))
                    else:
                        await send_whatsapp_message(sender_phone, "No active job found to tailor for.")
                else:
                    await send_whatsapp_message(sender_phone, "Phone number not linked to any CareerOS account.")
        except Exception as exc:
            logger.exception("Error checking pending tailor job: %s", exc)

    # Return standard Twilio TwiML / HTTP 200 OK
    return Response(
        content="<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>",
        media_type="application/xml",
    )
