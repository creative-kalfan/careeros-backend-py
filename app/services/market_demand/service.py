"""Market demand and skill gap analysis service."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import get_settings
from app.repositories.job_repository import JobRepository
from app.repositories.market_demand_repository import MarketDemandRepository
from app.repositories.resume_repository import ResumeRepository
from app.services.market_demand.curated_links import get_learning_links_for_skills

logger = logging.getLogger(__name__)


class MarketDemandService:
    """Provides market demand insights, skill trends, and skill gap roadmaps."""

    def __init__(
        self,
        market_repo: Optional[MarketDemandRepository] = None,
        job_repo: Optional[JobRepository] = None,
    ) -> None:
        self.market_repo = market_repo or MarketDemandRepository()
        self.job_repo = job_repo or JobRepository()

    async def get_market_demand(
        self,
        role_family: str = "Software Engineering",
        user_id: Optional[str] = None,
        auth_client: Any = None,
    ) -> dict[str, Any]:
        """Fetch market snapshot and calculate candidate skill gap roadmap if user profile available."""
        # Check DB for precomputed snapshot
        snapshot = await self.market_repo.get_latest_snapshot(role_family)
        if not snapshot:
            # Dynamically compute from active jobs
            all_jobs = self.job_repo.list_jobs(is_active=True, limit=500)
            family_jobs = [
                j for j in all_jobs
                if role_family.lower() in str(j.get("role_category") or "").lower()
                or role_family.lower() in str(j.get("title") or "").lower()
            ]
            if not family_jobs:
                family_jobs = all_jobs[:100]  # Fallback to general active jobs

            snapshot = await self.market_repo.compute_and_store_snapshot(
                role_family=role_family,
                active_jobs=family_jobs,
            )

        # Skill gap analysis against candidate's profile
        user_skills: set[str] = set()
        if user_id and auth_client:
            try:
                resume_repo = ResumeRepository(auth_client)
                resumes = resume_repo.list_resumes(user_id) or []
                for r in resumes:
                    profile = (r.get("content") or {}).get("profile") or {}
                    skills_data = profile.get("skills") or []
                    if isinstance(skills_data, list):
                        for item in skills_data:
                            if isinstance(item, dict):
                                for s in item.get("items") or []:
                                    user_skills.add(str(s).lower())
                            elif isinstance(item, str):
                                user_skills.add(item.lower())
            except Exception as exc:
                logger.debug("Failed to extract candidate skills for gap analysis: %s", exc)

        top_skills = snapshot.get("top_skills") or []
        gap_analysis = []
        missing_skills = []
        for item in top_skills:
            skill_name = item.get("skill")
            has_skill = skill_name.lower() in user_skills if user_skills else False
            if not has_skill:
                missing_skills.append(skill_name)
            gap_analysis.append({
                "skill": skill_name,
                "in_profile": has_skill,
                "frequency": item.get("count"),
                "percentage": item.get("percentage"),
            })

        learning_roadmap = get_learning_links_for_skills(missing_skills[:5])

        return {
            "role_family": role_family,
            "snapshot_date": snapshot.get("snapshot_date"),
            "sample_size": snapshot.get("sample_size", 0),
            "fresher_internship_share": snapshot.get("fresher_internship_share", 0.0),
            "top_skills": top_skills,
            "top_locations": snapshot.get("top_locations", []),
            "salary_stats": snapshot.get("salary_stats", {}),
            "weekly_trend": snapshot.get("weekly_trend", {}),
            "skill_gap": gap_analysis,
            "learning_roadmap": learning_roadmap,
        }
