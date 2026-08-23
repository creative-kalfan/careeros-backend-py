"""Recommendation service: orchestration layer."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.repositories.job_repository import JobRepository
from app.repositories.profile_repository import ProfileRepository
from app.repositories.recommendation_repository import RecommendationRepository
from app.services.recommendations.recommendation_engine import RecommendationEngine

logger = logging.getLogger(__name__)


class RecommendationService:
    """Orchestrates profile/resume/job loading and delegates ranking to the engine."""

    def __init__(
        self,
        job_repository: Optional[JobRepository] = None,
        profile_repository: Optional[ProfileRepository] = None,
        recommendation_repository: Optional[RecommendationRepository] = None,
        engine: Optional[RecommendationEngine] = None,
    ) -> None:
        self.job_repository = job_repository or JobRepository()
        self.profile_repository = profile_repository or ProfileRepository()
        self.recommendation_repository = recommendation_repository or RecommendationRepository()
        self.engine = engine or RecommendationEngine()

    async def generate_for_user(
        self,
        auth: Any,  # AuthContext
        status: Optional[str] = None,
        priority: Optional[str] = None,
        remote: Optional[bool] = None,
        min_score: Optional[float] = None,
        sort: str = "highest-score",
        limit: int = 50,
        saved: Optional[bool] = None,
        applied: Optional[bool] = None,
        dismissed: Optional[bool] = None,
        top_matches: Optional[bool] = None,
    ) -> list[dict[str, Any]]:
        """Generate ranked recommendations for the authenticated user.

        Steps:
        1. Try persisted recommendations first (hybrid); if none, generate dynamically.
        2. For dynamic: load profile, resume, candidate jobs, excluded ids, then rank.
        3. Apply query filters (status via excluded handling, remote, priority, minScore, sort, limit)
        """
        user_id = auth.user.id
        supabase = auth.supabase

        # Map legacy filter flags to status filter
        if saved:
            status = "SAVED"
        elif applied:
            status = "APPLIED"
        elif dismissed:
            status = "DISMISSED"

        # If caller explicitly filters by status/priority, try persisted first
        # but fallback to dynamic if persisted is None/empty
        # For generic listing without strict persisted requirement, prefer dynamic generation
        # to ensure fresh India-first ranking and profile-aware scoring.

        # Attempt to use persisted recommendations only if they exist and caller expects them
        # For now, generate dynamically always (hybrid with persistence opportunistic)
        dynamic = await self._generate_dynamic(
            auth=auth,
            remote=remote,
            priority=priority,
            min_score=min_score,
            sort=sort,
            limit=limit,
            top_matches=top_matches,
            status=status,
            saved=saved,
            applied=applied,
            dismissed=dismissed,
        )

        # If status filter targets persisted lifecycle (SAVED/DISMISSED/APPLIED), try to respect
        # persisted data by querying repository; if no persisted rows, return empty for those statuses
        if status in ("SAVED", "DISMISSED", "APPLIED"):
            persisted = await self.recommendation_repository.list_persisted(
                supabase, user_id, status=status, priority=priority, remote=remote,
                min_score=int(min_score) if min_score is not None else None,
                sort=sort, limit=limit,
            )
            if persisted is not None and len(persisted) > 0:
                # Return persisted shape normalized to API shape
                return self._normalize_persisted(persisted, limit)

            # If no persisted rows for this status, fall back: for DISMISSED/APPLIED return empty,
            # for SAVED try saved_jobs? For now return empty to avoid confusing dynamic with saved.
            if status in ("DISMISSED", "APPLIED"):
                return []
            # For SAVED, check saved_jobs as alternative
            if status == "SAVED":
                try:
                    result = await supabase.table("saved_jobs").select("*, jobs(*)").eq("user_id", user_id).order("created_at", ascending=False).limit(limit).execute()
                    rows = result.data or []
                    # Convert saved jobs to recommendation-like shape
                    recs = []
                    for row in rows:
                        job_row = row.get("jobs") or {}
                        recs.append({
                            "id": row.get("id") or job_row.get("id"),
                            "user_id": user_id,
                            "job_id": job_row.get("id"),
                            "match_score": 75,
                            "priority": "good",
                            "status": "SAVED",
                            "job": job_row,
                        })
                    return recs[:limit]
                except Exception:
                    return []

        return dynamic

    async def get_top(
        self,
        auth: Any,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get top recommendations (score >=80)."""
        # Try persisted top first
        persisted = await self.recommendation_repository.get_top_persisted(auth.supabase, auth.user.id, limit)
        if persisted and len(persisted) > 0:
            return self._normalize_persisted(persisted, limit)

        # Fallback dynamic top
        recs = await self._generate_dynamic(
            auth=auth,
            min_score=80,
            limit=limit,
            top_matches=True,
            sort="highest-score",
        )
        return recs[:limit]

    async def _generate_dynamic(
        self,
        auth: Any,
        remote: Optional[bool] = None,
        priority: Optional[str] = None,
        min_score: Optional[float] = None,
        sort: str = "highest-score",
        limit: int = 50,
        top_matches: Optional[bool] = None,
        status: Optional[str] = None,
        saved: Optional[bool] = None,
        applied: Optional[bool] = None,
        dismissed: Optional[bool] = None,
    ) -> list[dict[str, Any]]:
        user_id = auth.user.id
        supabase = auth.supabase

        # 1. Profile (sync service-role for simplicity; respectsservice but not RLS - fallback to async)
        profile: Optional[UserProfile] = None
        try:
            profile = self.profile_repository.get_profile(user_id)
        except Exception as exc:
            logger.debug("get_profile sync failed: %s", exc)
        if profile is None:
            try:
                # Try async RLS path
                from app.repositories.profile_repository import ProfileRepository as PR
                # Use auth.supabase async client: we need async aget_profile; create temp repo with that client
                tmp = PR(client=supabase)  # type: ignore
                profile = await tmp.aget_profile(user_id)  # type: ignore
            except Exception as exc:
                logger.debug("aget_profile failed: %s", exc)
                profile = None

        # Augment profile with resume-derived skills if available
        resume_id = await self.recommendation_repository.find_resume_id(supabase, user_id)
        if resume_id:
            try:
                # Try to enrich profile.skills with resume content skills
                resume_row = await supabase.table("resumes").select("content, parse_status").eq("id", resume_id).eq("user_id", user_id).maybe_single().execute()
                if resume_row and resume_row.data:
                    content = resume_row.data.get("content") or {}
                    # content may contain skills array
                    resume_skills = content.get("skills") or content.get("Skills") or []
                    if isinstance(resume_skills, list) and resume_skills:
                        # Merge unique skills
                        existing = set((profile.skills or []) if profile else [])
                        merged = list(existing.union(set(resume_skills)))
                        if profile:
                            profile.skills = merged
                        else:
                            profile = UserProfile(id=user_id, skills=merged)
            except Exception as exc:
                logger.debug("resume skill enrichment failed: %s", exc)

        # 2. Candidate jobs: fetch large candidate set, respect remote filter at DB level if cheap
        # Use JobRepository.list_jobs with big page to get active jobs
        # For remote filter, we post-filter; don't rely on DB column that may not exist in query
        try:
            db_rows, total = self.job_repository.list_jobs(page=1, page_size=500)
        except Exception as exc:
            logger.warning("list_jobs failed: %s", exc)
            db_rows, total = [], 0

        # Build NormalizedJob objects preserving id
        jobs: list[NormalizedJob] = []
        for row in db_rows:
            try:
                job = NormalizedJob.model_validate(row)
                # Stash DB id for recommendation output (NormalizedJob has no id field)
                object.__setattr__(job, "id", row.get("id"))
                jobs.append(job)
            except Exception:
                continue

        # 3. Excluded job ids (dismissed/applied)
        excluded = await self.recommendation_repository.get_excluded_job_ids(supabase, user_id)

        # 4. Rank via engine
        # Determine threshold
        effective_min = None
        if min_score is not None:
            effective_min = int(min_score)
        elif top_matches:
            effective_min = 80

        # Use engine threshold filtering; if min_score not set, engine default 60
        ranked = self.engine.rank(
            jobs=jobs,
            profile=profile,
            excluded_job_ids=excluded,
            min_score=effective_min if effective_min is not None else 60,
            limit=None,
            include_below_threshold=(effective_min is None),
        )

        # Post-filters: remote, priority, min_score (if threshold was inclusive vs exclusive)
        filtered = ranked
        if remote is not None:
            filtered = [r for r in filtered if bool(r["job"].remote) is bool(remote)]

        if priority:
            filtered = [r for r in filtered if r.get("priority") == priority]

        if effective_min is not None:
            filtered = [r for r in filtered if r["recommendation_score"] >= effective_min]
        elif top_matches:
            filtered = [r for r in filtered if r["recommendation_score"] >= 80]

        # Sort handling
        if sort == "newest":
            # Sort by posted_date desc then score
            def _posted_key(r):
                pd = r["job"].posted_date or ""
                return pd
            filtered.sort(key=lambda r: (_posted_key(r), r["recommendation_score"]), reverse=True)
        else:
            # Already sorted by score+india+freshness
            pass

        filtered = filtered[: min(limit, 100)]

        # Convert to API records
        records = [
            self.engine.to_recommendation_record(r, user_id=user_id, resume_id=resume_id)
            for r in filtered
        ]
        return records

    def _normalize_persisted(self, rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        """Normalize persisted rows to API shape (adds camelCase aliases)."""
        out = []
        for row in rows[:limit]:
            job = row.get("jobs") or row.get("job") or {}
            rec = {
                **row,
                "job": job,
                "jobId": row.get("job_id"),
                "resumeId": row.get("resume_id"),
                "matchScore": row.get("match_score"),
                "skillMatch": row.get("skill_match"),
                "keywordMatch": row.get("keyword_match"),
                "semanticSimilarity": row.get("semantic_similarity"),
                "recommendationReason": row.get("recommendation_reason") or [],
            }
            out.append(rec)
        return out
