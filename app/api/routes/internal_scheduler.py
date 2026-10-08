"""Internal scheduler trigger: one bounded crawl dispatch tick per call.

Called by GitHub Actions cron (.github/workflows/crawl-scheduler.yml). This
route only claims due crawl_targets and enqueues ARQ jobs via the existing
dispatcher; crawling itself always runs in the ARQ worker.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings
from app.services.jobs import crawl_dispatcher

router = APIRouter(prefix="/internal/scheduler", tags=["internal"])


@router.post("/crawl-tick")
async def crawl_tick(authorization: str | None = Header(default=None)) -> dict:
    settings = get_settings()
    secret = settings.scheduler_trigger_secret
    if not secret:
        raise HTTPException(status_code=503, detail="Scheduler trigger is not configured.")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(token.encode(), secret.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized.")
    if not settings.job_crawl_enabled:
        return {"status": "disabled", "enqueued": 0, "analysis_backfill_enqueued": 0}
    summary = await crawl_dispatcher.run_dispatch_tick({})
    return {"status": "ok", **summary}
