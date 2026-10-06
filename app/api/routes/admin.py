"""Small token-protected operational crawl summary."""

from __future__ import annotations

import asyncio
import hmac
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings
from app.db.supabase import get_service_client

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)


@router.get("/crawl-status")
async def crawl_status(admin_status_token: str | None = Header(default=None, alias="ADMIN_STATUS_TOKEN")) -> dict:
    settings = get_settings()
    if not settings.admin_status_token or not admin_status_token or not hmac.compare_digest(
        settings.admin_status_token, admin_status_token
    ):
        raise HTTPException(status_code=403, detail={"code": "ADMIN_FORBIDDEN", "message": "Forbidden"})

    def load() -> dict:
        client = get_service_client()
        targets = client.table("crawl_targets").select(
            "source,slug,status,next_run_at,last_job_count,last_error"
        ).execute().data or []
        now = datetime.now(timezone.utc)
        overdue = 0
        dead_targets = []
        crawl_lag = 0
        yields: dict[str, dict[str, int]] = {}
        for row in targets:
            if row.get("status") == "dead":
                dead_targets.append({"source": row["source"], "slug": row["slug"], "last_error": row.get("last_error")})
            due = _date(row.get("next_run_at"))
            is_overdue = row.get("status") == "active" and due is not None and due < now
            overdue += int(is_overdue)
            if is_overdue:
                crawl_lag = max(crawl_lag, int((now - due).total_seconds()))
            entry = yields.setdefault(row["source"], {"targets": 0, "jobs": 0})
            entry["targets"] += 1
            entry["jobs"] += int(row.get("last_job_count") or 0)
        result: dict[str, int] = {}
        for label, days in (("24h", 1), ("7d", 7)):
            count = client.table("jobs").select("id", count="exact").gte(
                "created_at", (now - timedelta(days=days)).isoformat()
            ).execute().count or 0
            result[label] = count

        from app.repositories.observability_repository import ObservabilityRepository
        obs_repo = ObservabilityRepository(client=client)
        obs_summary = obs_repo.get_crawl_observability_summary(hours=24, last_n_runs=10)

        return {
            "crawl_lag_seconds": crawl_lag,
            "overdue_count": overdue,
            "dead_targets": dead_targets,
            "jobs_added": result,
            "yield_by_source": yields,
            "anomalies_24h": obs_summary.get("anomalies_24h", []),
            "last_runs_by_source": obs_summary.get("last_runs_by_source", {}),
            "jobs_per_day_by_source": obs_summary.get("jobs_per_day_by_source", {}),
            "median_timing_ms": obs_summary.get("median_timing_ms", {"fetch_ms": 0, "persist_ms": 0}),
            "observability_enabled": obs_summary.get("available", False),
        }

    try:
        return await asyncio.to_thread(load)
    except Exception as exc:
        logger.exception("crawl status query failed")
        raise HTTPException(status_code=503, detail={"code": "CRAWL_STATUS_UNAVAILABLE", "message": "Crawl status is unavailable"}) from exc


def _date(value: str | None) -> datetime | None:
    try:
        if not value:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None
