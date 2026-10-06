"""Market demand repository.

Provides data-access and snapshot generation for role families, skills,
fresher/internship share, salary distributions, and weekly trends.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MarketDemandRepository:
    """Persistence and aggregation layer for market demand snapshots."""

    def __init__(self, supabase: Any = None) -> None:
        self._supabase = supabase

    def _get_client(self) -> Any:
        if self._supabase is not None:
            return self._supabase
        from app.db.client import get_supabase_client
        return get_supabase_client()

    async def get_latest_snapshot(self, role_family: str) -> Optional[dict[str, Any]]:
        """Fetch the most recent market demand snapshot for a given role family."""
        supabase = self._get_client()
        try:
            res = (
                supabase.table("market_snapshots")
                .select("*")
                .eq("role_family", role_family)
                .order("snapshot_date", desc=True)
                .limit(1)
                .execute()
            )
            result = await res if hasattr(res, "__await__") else res
            data = getattr(result, "data", None)
            if data and isinstance(data, list) and len(data) > 0:
                return data[0]
        except Exception as exc:
            logger.warning("Failed to fetch market snapshot from DB: %s", exc)
        return None

    async def compute_and_store_snapshot(
        self,
        role_family: str,
        active_jobs: list[dict[str, Any]],
        snapshot_date: Optional[datetime.date] = None,
    ) -> dict[str, Any]:
        """Compute aggregate stats from active jobs in this role family and persist snapshot."""
        today = snapshot_date or datetime.date.today()
        n = len(active_jobs)
        if n == 0:
            snapshot = {
                "snapshot_date": today.isoformat(),
                "role_family": role_family,
                "sample_size": 0,
                "top_skills": [],
                "fresher_internship_share": 0.0,
                "top_locations": [],
                "salary_stats": {},
                "weekly_trend": {},
            }
            return snapshot

        # 1. Top skills (count and percentage)
        skill_counts: dict[str, int] = {}
        for job in active_jobs:
            skills = job.get("skills") or []
            if isinstance(skills, list):
                for s in skills:
                    s_clean = str(s).strip()
                    if s_clean:
                        skill_counts[s_clean] = skill_counts.get(s_clean, 0) + 1

        sorted_skills = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:15]
        top_skills = [
            {"skill": s, "count": count, "percentage": round((count / n) * 100, 1)}
            for s, count in sorted_skills
        ]

        # 2. Fresher / Internship share
        fresher_count = 0
        for job in active_jobs:
            title = str(job.get("title") or "").lower()
            exp = str(job.get("experience_level") or "").lower()
            emp = str(job.get("employment_type") or "").lower()
            if any(term in title or term in exp or term in emp for term in ("intern", "fresher", "entry", "graduate")):
                fresher_count += 1
        fresher_share = round((fresher_count / n) * 100, 1)

        # 3. Top locations
        loc_counts: dict[str, int] = {}
        for job in active_jobs:
            loc = str(job.get("location") or "Unknown").strip()
            loc_counts[loc] = loc_counts.get(loc, 0) + 1
        sorted_locs = sorted(loc_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        top_locations = [{"location": loc, "count": count} for loc, count in sorted_locs]

        # 4. Salary statistics (min, max, median where present)
        salaries: list[float] = []
        for job in active_jobs:
            s_min = job.get("salary_min")
            s_max = job.get("salary_max")
            if s_min is not None and s_max is not None:
                salaries.append((float(s_min) + float(s_max)) / 2.0)
            elif s_min is not None:
                salaries.append(float(s_min))
            elif s_max is not None:
                salaries.append(float(s_max))

        salary_stats: dict[str, Any] = {}
        if salaries:
            salaries.sort()
            s_len = len(salaries)
            median = salaries[s_len // 2] if s_len % 2 != 0 else (salaries[s_len // 2 - 1] + salaries[s_len // 2]) / 2.0
            salary_stats = {
                "count": s_len,
                "min": round(salaries[0], 2),
                "max": round(salaries[-1], 2),
                "median": round(median, 2),
            }

        # 5. Weekly trend from first_seen_at
        week_counts: dict[str, int] = {}
        now = datetime.datetime.now(datetime.timezone.utc)
        for job in active_jobs:
            fs = job.get("first_seen_at") or job.get("created_at")
            if fs:
                try:
                    dt = datetime.datetime.fromisoformat(str(fs).replace("Z", "+00:00"))
                    days_ago = (now - dt).days
                    if days_ago <= 28:
                        week_bin = f"week_{days_ago // 7 + 1}"
                        week_counts[week_bin] = week_counts.get(week_bin, 0) + 1
                except Exception:
                    pass

        snapshot = {
            "snapshot_date": today.isoformat(),
            "role_family": role_family,
            "sample_size": n,
            "top_skills": top_skills,
            "fresher_internship_share": fresher_share,
            "top_locations": top_locations,
            "salary_stats": salary_stats,
            "weekly_trend": week_counts,
        }

        # Persist to DB (graceful fallback if table does not exist)
        try:
            supabase = self._get_client()
            res = (
                supabase.table("market_snapshots")
                .upsert(snapshot, on_conflict="snapshot_date,role_family")
                .execute()
            )
            if hasattr(res, "__await__"):
                await res
        except Exception as exc:
            logger.warning("Could not persist market_snapshots to Supabase: %s", exc)

        return snapshot
