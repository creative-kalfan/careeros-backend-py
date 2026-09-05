"""ARQ background job for interview preparation generation.

Used when ``POST /api/interview-prep/generate`` is called with
``async_mode=true``. The worker uses the service-role client but enforces
user ownership at the service/repository boundary: the session row is
fetched by ``(id, user_id)`` and generation aborts when the owner does not
match. No credentials travel in the job payload — only ids.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from app.workers.registry import register_job

logger = logging.getLogger(__name__)


@register_job(
    "generate_interview_prep_job",
    timeout=300,
    max_tries=2,
    retry=True,
    description="Generate interview preparation questions for a session in the background.",
)
async def generate_interview_prep_job(
    ctx: dict[str, Any],
    session_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Generate questions for a ``generating`` prep session."""
    from app.db.supabase import get_service_client
    from app.repositories.application_repository import ApplicationRepository
    from app.repositories.interview_prep_repository import InterviewPrepRepository
    from app.services.interview_prep.service import InterviewPrepService

    if not session_id or not user_id:
        raise ValueError("Missing required job fields: session_id, user_id")

    service_client = get_service_client()
    repo = InterviewPrepRepository()
    session = await repo.get_session(service_client, user_id, session_id)
    if session is None:
        # Ownership failure or unknown session — fail loudly, never generate
        # for the wrong owner.
        raise ValueError(f"Prep session {session_id} not found for user {user_id}")
    if session.get("status") != "generating":
        return {"success": True, "session_id": session_id, "status": session.get("status"), "skipped": True}

    # Minimal auth-like namespace backed by the service client. Ownership is
    # enforced because every repository call below filters on user_id and the
    # session was already verified to belong to user_id above.
    worker_auth = SimpleNamespace(
        supabase=service_client,
        user=SimpleNamespace(id=user_id),
        jwt=None,
    )
    service = InterviewPrepService(
        repository=repo,
        application_repository=ApplicationRepository(),
    )
    requested = int((session.get("source_metadata") or {}).get("question_count_requested") or 8)
    gather = await service._gather_context(
        worker_auth,
        str(session["application_id"]),
        session.get("interview_id"),
        session.get("source_resume_id"),
        session.get("job_id"),
    )
    result = await service._run_generation(worker_auth, session, gather, requested)
    return {
        "success": result.get("status") == "ready",
        "session_id": session_id,
        "status": result.get("status"),
    }
