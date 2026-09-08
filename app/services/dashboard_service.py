"""Dashboard telemetry service: aggregates user metrics from Supabase."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.schemas.dashboard import TimelineItem

logger = logging.getLogger(__name__)


class DashboardService:
    """Aggregate telemetry data for the authenticated user's dashboard."""

    def __init__(self, supabase: Any) -> None:
        self._supabase = supabase

    async def get_user_telemetry(self, user_id: str) -> dict[str, Any]:
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

    async def _get_resume_ids(self, user_id: str) -> list[str]:
        result = await (
            self._supabase.table("resumes")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        rows = result.data or []
        return [r["id"] for r in rows if r.get("id")]

    async def _count_resumes(self, user_id: str) -> int:
        result = await (
            self._supabase.table("resumes")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .execute()
        )
        return result.count or 0

    async def _count_tailored_versions(self, resume_ids: list[str]) -> int:
        if not resume_ids:
            return 0
        result = await (
            self._supabase.table("resume_versions")
            .select("id", count="exact")
            .in_("resume_id", resume_ids)
            .eq("is_master", False)
            .execute()
        )
        return result.count or 0

    async def _count_applications(self, user_id: str) -> int:
        result = await (
            self._supabase.table("applications")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .execute()
        )
        return result.count or 0

    async def _avg_ats_score(self, resume_ids: list[str]) -> float | None:
        if not resume_ids:
            return None
        result = await (
            self._supabase.table("resume_ats_analyses")
            .select("overall_score")
            .in_("resume_id", resume_ids)
            .execute()
        )
        rows = result.data or []
        scores = [r["overall_score"] for r in rows if r.get("overall_score") is not None]
        if not scores:
            return None
        return round(sum(scores) / len(scores), 2)

    async def _count_active_jobs(self, user_id: str) -> int:
        result = await (
            self._supabase.table("resumes")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("parse_status", "processing")
            .execute()
        )
        return result.count or 0

    async def _build_timeline(self, user_id: str, resume_ids: list[str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        version_task = self._recent_resume_versions(resume_ids)
        application_task = self._recent_applications(user_id)
        ats_task = self._recent_ats_analyses(resume_ids)
        resume_task = self._recent_resumes(user_id)

        version_rows, app_rows, ats_rows, resume_rows = await asyncio.gather(
            version_task, application_task, ats_task, resume_task
        )

        items.extend(version_rows)
        items.extend(app_rows)
        items.extend(ats_rows)
        items.extend(resume_rows)

        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items[:10]

    async def _recent_resume_versions(self, resume_ids: list[str]) -> list[dict[str, Any]]:
        if not resume_ids:
            return []
        result = await (
            self._supabase.table("resume_versions")
            .select("id, version_name, created_at, resume_id, target_job_title, target_company")
            .in_("resume_id", resume_ids)
            .eq("is_master", False)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        rows = result.data or []
        return [
            {
                "action": "tailored_version_created",
                "description": self._format_version_description(r),
                "timestamp": r.get("created_at", ""),
                "metadata": {"version_id": r["id"], "resume_id": r.get("resume_id")},
            }
            for r in rows
            if r.get("created_at")
        ]

    async def _recent_applications(self, user_id: str) -> list[dict[str, Any]]:
        result = await (
            self._supabase.table("applications")
            .select("id, job_title, company_name, application_date, created_at")
            .eq("user_id", user_id)
            .order("application_date", desc=True)
            .limit(5)
            .execute()
        )
        rows = result.data or []
        return [
            {
                "action": "application_tracked",
                "description": f"Tracking {r.get('job_title', 'a role')} at {r.get('company_name', '')}".strip(),
                "timestamp": r.get("application_date") or r.get("created_at", ""),
                "metadata": {"application_id": r["id"]},
            }
            for r in rows
            if (r.get("application_date") or r.get("created_at"))
        ]

    async def _recent_ats_analyses(self, resume_ids: list[str]) -> list[dict[str, Any]]:
        if not resume_ids:
            return []
        result = await (
            self._supabase.table("resume_ats_analyses")
            .select("id, overall_score, created_at, resume_id, job_title, company")
            .in_("resume_id", resume_ids)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        rows = result.data or []
        return [
            {
                "action": "ats_analysis_completed",
                "description": self._format_ats_description(r),
                "timestamp": r.get("created_at", ""),
                "metadata": {"analysis_id": r["id"], "score": r.get("overall_score")},
            }
            for r in rows
            if r.get("created_at")
        ]

    async def _recent_resumes(self, user_id: str) -> list[dict[str, Any]]:
        result = await (
            self._supabase.table("resumes")
            .select("id, title, parse_status, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        rows = result.data or []
        return [
            {
                "action": "resume_created",
                "description": f"Created resume '{r.get('title', 'Untitled')}'",
                "timestamp": r.get("created_at", ""),
                "metadata": {"resume_id": r["id"], "parse_status": r.get("parse_status")},
            }
            for r in rows
            if r.get("created_at")
        ]

    @staticmethod
    def _format_version_description(row: dict[str, Any]) -> str:
        title = row.get("target_job_title") or row.get("version_name", "Version")
        company = row.get("target_company") or ""
        if company:
            return f"Tailored '{title}' at {company}"
        return f"Created variant '{title}'"

    @staticmethod
    def _format_ats_description(row: dict[str, Any]) -> str:
        title = row.get("job_title") or "a role"
        company = row.get("company") or ""
        score = row.get("overall_score")
        score_text = f" — score {score}" if score is not None else ""
        if company:
            return f"ATS analysis for {title} at {company}{score_text}"
        return f"ATS analysis for {title}{score_text}"
