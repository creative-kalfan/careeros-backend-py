"""Dashboard telemetry service: aggregates user metrics from Supabase."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any

from app.schemas.dashboard import EMPTY_TELEMETRY, TimelineItem

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_iso8601(value: Any) -> str:
    """Normalize any Supabase timestamp to an ISO 8601 string.

    Accepts ``datetime``/``date`` objects, ISO strings (including ``Z``),
    and epoch numbers. ``None``/missing/unparseable values fall back to
    ``now()`` so the timeline never crashes on null dates and the frontend
    always receives a parseable string.
    """
    if value is None:
        return _utcnow_iso()
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return _utcnow_iso()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return _utcnow_iso()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            return _utcnow_iso()
    return _utcnow_iso()


def _rows(result: Any) -> list[dict[str, Any]]:
    """Extract dict rows from a Supabase response, tolerating nulls."""
    if result is None:
        return []
    data = getattr(result, "data", None)
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


def _count(result: Any) -> int:
    """Extract an exact count from a Supabase response, defaulting to 0."""
    if result is None:
        return 0
    count = getattr(result, "count", None)
    if isinstance(count, bool):
        return 0
    if isinstance(count, (int, float)):
        return max(0, int(count))
    return 0


class DashboardService:
    """Aggregate telemetry data for the authenticated user's dashboard."""

    def __init__(self, supabase: Any) -> None:
        self._supabase = supabase

    async def get_user_telemetry(self, user_id: str) -> dict[str, Any]:
        """Return telemetry with safe defaults; never raises.

        Any sub-query failure (missing tables, RLS errors, null aggregates)
        is logged and the dashboard falls back to an empty payload with
        HTTP 200 instead of a 500.
        """
        try:
            resume_ids = await self._get_resume_ids(user_id)

            total_resumes, tailored_versions, applications_tracked, avg_score, active_jobs = await asyncio.gather(
                self._count_resumes(user_id),
                self._count_tailored_versions(resume_ids),
                self._count_applications(user_id),
                self._avg_ats_score(resume_ids),
                self._count_active_jobs(user_id),
            )

            timeline = await self._build_timeline(user_id, resume_ids)

            return {
                "total_resumes": total_resumes,
                "tailored_versions": tailored_versions,
                "applications_tracked": applications_tracked,
                "average_ats_score": avg_score,
                "active_jobs_in_queue": active_jobs,
                "activity_timeline": timeline,
            }
        except Exception:
            logger.exception("Dashboard telemetry failed for user %s; returning empty payload", user_id)
            return dict(EMPTY_TELEMETRY)

    async def _get_resume_ids(self, user_id: str) -> list[str]:
        try:
            result = await (
                self._supabase.table("resumes")
                .select("id")
                .eq("user_id", user_id)
                .execute()
            )
            return [str(r["id"]) for r in _rows(result) if r.get("id") is not None]
        except Exception:
            logger.exception("Dashboard _get_resume_ids failed; defaulting to []")
            return []

    async def _count_resumes(self, user_id: str) -> int:
        try:
            result = await (
                self._supabase.table("resumes")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .execute()
            )
            return _count(result)
        except Exception:
            logger.exception("Dashboard _count_resumes failed; defaulting to 0")
            return 0

    async def _count_tailored_versions(self, resume_ids: list[str]) -> int:
        if not resume_ids:
            return 0
        try:
            result = await (
                self._supabase.table("resume_versions")
                .select("id", count="exact")
                .in_("resume_id", resume_ids)
                .eq("is_master", False)
                .execute()
            )
            return _count(result)
        except Exception:
            logger.exception("Dashboard _count_tailored_versions failed; defaulting to 0")
            return 0

    async def _count_applications(self, user_id: str) -> int:
        try:
            result = await (
                self._supabase.table("applications")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .execute()
            )
            return _count(result)
        except Exception:
            logger.exception("Dashboard _count_applications failed; defaulting to 0")
            return 0

    async def _avg_ats_score(self, resume_ids: list[str]) -> float:
        if not resume_ids:
            return 0.0
        try:
            result = await (
                self._supabase.table("resume_ats_analyses")
                .select("overall_score")
                .in_("resume_id", resume_ids)
                .execute()
            )
            scores: list[float] = []
            for r in _rows(result):
                score = r.get("overall_score")
                if isinstance(score, bool):
                    continue
                if isinstance(score, (int, float)):
                    scores.append(float(score))
            if not scores:
                return 0.0
            return round(sum(scores) / len(scores), 2)
        except Exception:
            logger.exception("Dashboard _avg_ats_score failed; defaulting to 0.0")
            return 0.0

    async def _count_active_jobs(self, user_id: str) -> int:
        try:
            result = await (
                self._supabase.table("resumes")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("parse_status", "processing")
                .execute()
            )
            return _count(result)
        except Exception:
            logger.exception("Dashboard _count_active_jobs failed; defaulting to 0")
            return 0

    async def _build_timeline(self, user_id: str, resume_ids: list[str]) -> list[dict[str, Any]]:
        try:
            version_rows, app_rows, ats_rows, resume_rows = await asyncio.gather(
                self._recent_resume_versions(resume_ids),
                self._recent_applications(user_id),
                self._recent_ats_analyses(resume_ids),
                self._recent_resumes(user_id),
            )
            items: list[dict[str, Any]] = []
            items.extend(version_rows)
            items.extend(app_rows)
            items.extend(ats_rows)
            items.extend(resume_rows)
            items.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
            return items[:10]
        except Exception:
            logger.exception("Dashboard _build_timeline failed; defaulting to []")
            return []

    async def _recent_resume_versions(self, resume_ids: list[str]) -> list[dict[str, Any]]:
        if not resume_ids:
            return []
        try:
            result = await (
                self._supabase.table("resume_versions")
                .select("id, version_name, created_at, resume_id, target_job_title, target_company")
                .in_("resume_id", resume_ids)
                .eq("is_master", False)
                .order("created_at", desc=True)
                .limit(5)
                .execute()
            )
            items: list[dict[str, Any]] = []
            for r in _rows(result):
                if r.get("id") is None:
                    continue
                raw_ts = r.get("created_at") or r.get("updated_at")
                item = TimelineItem(
                    action="tailored_version_created",
                    description=self._format_version_description(r),
                    timestamp=to_iso8601(raw_ts),
                    metadata={"version_id": r.get("id"), "resume_id": r.get("resume_id")},
                )
                items.append(item.model_dump())
            return items
        except Exception:
            logger.exception("Dashboard _recent_resume_versions failed; defaulting to []")
            return []

    async def _recent_applications(self, user_id: str) -> list[dict[str, Any]]:
        try:
            result = await (
                self._supabase.table("applications")
                .select("id, job_title, company_name, application_date, created_at")
                .eq("user_id", user_id)
                .order("application_date", desc=True)
                .limit(5)
                .execute()
            )
            items: list[dict[str, Any]] = []
            for r in _rows(result):
                if r.get("id") is None:
                    continue
                raw_ts = r.get("application_date") or r.get("created_at") or r.get("updated_at")
                item = TimelineItem(
                    action="application_tracked",
                    description=f"Tracking {r.get('job_title') or 'a role'} at {r.get('company_name') or ''}".strip(),
                    timestamp=to_iso8601(raw_ts),
                    metadata={"application_id": r.get("id")},
                )
                items.append(item.model_dump())
            return items
        except Exception:
            logger.exception("Dashboard _recent_applications failed; defaulting to []")
            return []

    async def _recent_ats_analyses(self, resume_ids: list[str]) -> list[dict[str, Any]]:
        if not resume_ids:
            return []
        try:
            result = await (
                self._supabase.table("resume_ats_analyses")
                .select("id, overall_score, created_at, resume_id, job_title, company")
                .in_("resume_id", resume_ids)
                .order("created_at", desc=True)
                .limit(5)
                .execute()
            )
            items: list[dict[str, Any]] = []
            for r in _rows(result):
                if r.get("id") is None:
                    continue
                raw_ts = r.get("created_at") or r.get("updated_at")
                item = TimelineItem(
                    action="ats_analysis_completed",
                    description=self._format_ats_description(r),
                    timestamp=to_iso8601(raw_ts),
                    metadata={"analysis_id": r.get("id"), "score": r.get("overall_score")},
                )
                items.append(item.model_dump())
            return items
        except Exception:
            logger.exception("Dashboard _recent_ats_analyses failed; defaulting to []")
            return []

    async def _recent_resumes(self, user_id: str) -> list[dict[str, Any]]:
        try:
            result = await (
                self._supabase.table("resumes")
                .select("id, title, parse_status, created_at")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(5)
                .execute()
            )
            items: list[dict[str, Any]] = []
            for r in _rows(result):
                if r.get("id") is None:
                    continue
                raw_ts = r.get("created_at") or r.get("updated_at")
                item = TimelineItem(
                    action="resume_created",
                    description=f"Created resume '{r.get('title') or 'Untitled'}'",
                    timestamp=to_iso8601(raw_ts),
                    metadata={"resume_id": r.get("id"), "parse_status": r.get("parse_status")},
                )
                items.append(item.model_dump())
            return items
        except Exception:
            logger.exception("Dashboard _recent_resumes failed; defaulting to []")
            return []

    @staticmethod
    def _format_version_description(row: dict[str, Any]) -> str:
        title = row.get("target_job_title") or row.get("version_name") or "Version"
        company = row.get("target_company") or ""
        if company:
            return f"Tailored '{title}' at {company}"
        return f"Created variant '{title}'"

    @staticmethod
    def _format_ats_description(row: dict[str, Any]) -> str:
        title = row.get("job_title") or "a role"
        company = row.get("company") or ""
        score = row.get("overall_score")
        score_text = f" — score {score}" if isinstance(score, (int, float)) and not isinstance(score, bool) else ""
        if company:
            return f"ATS analysis for {title} at {company}{score_text}"
        return f"ATS analysis for {title}{score_text}"
