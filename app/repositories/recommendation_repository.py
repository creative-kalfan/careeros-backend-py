"""Recommendation repository: access to recommendations, saved_jobs, applications.

Gracefully handles missing tables (e.g., if legacy migration not applied) by
returning empty results instead of raising.
"""

from __future__ import annotations

from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class RecommendationRepository:
    """Data-access helpers for recommendation-related tables."""

    async def get_excluded_job_ids(
        self,
        supabase: Any,
        user_id: str,
    ) -> set[str]:
        """Collect job ids the user should not be recommended.

        - Jobs with recommendations status DISMISSED / APPLIED
        - Jobs user already applied to (applications table may use job_title/company)
        - Saved jobs are NOT excluded (they are positive signal)
        """
        excluded: set[str] = set()

        # 1. Dismissed / applied recommendations
        try:
            result = await supabase.table("recommendations").select("job_id, status").eq("user_id", user_id).in_("status", ["DISMISSED", "APPLIED"]).execute()
            for row in (result.data or []):
                if row.get("job_id"):
                    excluded.add(str(row["job_id"]))
        except Exception as exc:
            logger.debug("recommendations table query failed (may not exist): %s", exc)

        # 2. Applications: try job_id column first, fallback to title/company matching not needed for id exclusion
        try:
            result = await supabase.table("applications").select("job_id").eq("user_id", user_id).execute()
            for row in (result.data or []):
                jid = row.get("job_id")
                if jid:
                    excluded.add(str(jid))
        except Exception as exc:
            logger.debug("applications job_id query failed: %s", exc)

        return excluded

    async def list_persisted(
        self,
        supabase: Any,
        user_id: str,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        remote: Optional[bool] = None,
        min_score: Optional[int] = None,
        sort: str = "highest-score",
        limit: int = 50,
    ) -> Optional[list[dict[str, Any]]]:
        """Try to list persisted recommendations; return None if table missing."""
        try:
            query = supabase.table("recommendations").select("*, jobs(*)").eq("user_id", user_id)
            if status:
                query = query.eq("status", status)
            if priority:
                query = query.eq("priority", priority)
            if min_score is not None:
                query = query.gte("match_score", min_score)
            # remote filter requires join; not supported via simple eq on recommendations, skip if needed handled post-filter
            if sort == "newest":
                query = query.order("created_at", desc=True)
            else:
                query = query.order("match_score", desc=True)
            query = query.limit(min(limit, 100))
            result = await query.execute()
            return result.data or []
        except Exception as exc:
            logger.debug("list_persisted failed: %s", exc)
            return None

    async def get_top_persisted(
        self,
        supabase: Any,
        user_id: str,
        limit: int = 5,
    ) -> Optional[list[dict[str, Any]]]:
        try:
            result = await supabase.table("recommendations").select("*, jobs(*)").eq("user_id", user_id).gte("match_score", 80).order("match_score", desc=True).limit(limit).execute()
            return result.data or []
        except Exception as exc:
            logger.debug("get_top_persisted failed: %s", exc)
            return None

    async def find_resume_id(self, supabase: Any, user_id: str) -> Optional[str]:
        """Return the most recent resume id for the user, if any."""
        try:
            result = await supabase.table("resumes").select("id").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()
            rows = result.data or []
            return rows[0]["id"] if rows else None
        except Exception as exc:
            logger.debug("find_resume_id failed: %s", exc)
            return None
