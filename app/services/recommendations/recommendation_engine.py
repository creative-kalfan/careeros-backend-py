"""Recommendation engine: core business logic for ranking jobs."""

from __future__ import annotations

import re
from typing import Any, Optional

from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.services.jobs.personalized_job_service import PersonalizedJobService
from app.services.jobs.source_priority import combined_rank_score
from app.services.recommendations.recommendation_reason_generator import RecommendationReasonGenerator
from app.services.recommendations.recommendation_scorer import RecommendationScorer

# India tokens mirror job_relevance_service._INDIA_TOKENS
_INDIA_TOKENS = [
    "india", "bengaluru", "bangalore", "hyderabad", "mumbai", "pune",
    "chennai", "delhi", "gurgaon", "gurugram", "noida", "kolkata",
    "ahmedabad", "kochi", "cochin", "indore", "jaipur", "chandigarh",
    "remote - india", "remote india",
]


def _india_first_score(job: NormalizedJob) -> int:
    location = (job.location or "").lower()
    if any(t in location for t in _INDIA_TOKENS):
        return 2
    if job.remote or "remote" in location:
        return 1
    return 0


class RecommendationEngine:
    """Deterministic, explainable recommendation engine.

    Responsibilities:
    - Score each candidate job via PersonalizedJobService (reuse, no duplicate algorithm)
    - Apply RecommendationScorer priority mapping
    - Generate explainable reasons via RecommendationReasonGenerator
    - Compute matched/missing skills, role/location/experience relevance
    - Sort by recommendation score DESC, India-first as tiebreaker, freshness tiebreaker
    - Does NOT touch DB or HTTP; pure business logic
    """

    def __init__(
        self,
        personalized_service: Optional[PersonalizedJobService] = None,
        scorer: Optional[RecommendationScorer] = None,
        reason_generator: Optional[RecommendationReasonGenerator] = None,
    ) -> None:
        self.personalized = personalized_service or PersonalizedJobService()
        self.scorer = scorer or RecommendationScorer()
        self.reason_gen = reason_generator or RecommendationReasonGenerator()

    def rank(
        self,
        jobs: list[NormalizedJob],
        profile: Optional[UserProfile],
        excluded_job_ids: Optional[set[str]] = None,
        min_score: int = 60,
        limit: Optional[int] = None,
        include_below_threshold: bool = False,
    ) -> list[dict[str, Any]]:
        """Rank jobs and return recommendation dicts.

        Each dict contains:
            job, match (8 factors), recommendation_score, priority, level,
            reasons, matched_skills, missing_skills, role_relevance,
            location_relevance, experience_relevance, india_score, etc.
        """
        if excluded_job_ids is None:
            excluded_job_ids = set()

        # Pre-filter role category if profile has desired_role (reuse filter logic)
        filtered = self.personalized.filter_jobs(jobs, profile) if profile and profile.desired_role else jobs

        results: list[dict[str, Any]] = []
        for job in filtered:
            # Skip explicitly excluded (applied/dismissed)
            job_id = getattr(job, "id", None) or getattr(job, "external_job_id", None) or ""
            # We store job ids from DB rows as 'id' attribute via model; if missing use title/company fallback not ideal
            # The caller passes excluded_job_ids as string ids; we try both id and external_job_id
            if job_id and job_id in excluded_job_ids:
                continue
            # Also check string representation fallback
            candidate_ids = {str(job_id)} if job_id else set()
            if candidate_ids & excluded_job_ids:
                continue

            match = self.personalized.calculate_match_score(job, profile)
            overall = match.get("overall", 0)
            scored = self.scorer.score(overall)

            if not include_below_threshold and not scored["should_recommend"]:
                # Still include if no threshold? For recommendation engine we filter <60 unless caller asks
                continue

            matched_skills, missing_skills = self._compute_skill_overlap(job, profile)

            # For role/location/experience relevance we reuse individual factor scores
            reasons = self.reason_gen.generate(match, job, profile, scored, matched_skills, missing_skills)

            # Determine job identifier for output (prefer id if model has it else external_job_id)
            # NormalizedJob doesn't have 'id' field by default; we handle via getattr
            raw_id = getattr(job, "id", None)
            # If job came from DB row via model_validate, id won't be on model but we can stash it
            # Caller should have passed jobs with id in model_dump extra; we fallback to external_job_id
            out_job_id = raw_id or job.external_job_id or job.title

            results.append({
                "job": job,
                "job_id": out_job_id,
                "match": match,
                "recommendation_score": scored["score"],
                "priority": scored["priority"],
                "level": scored["level"],
                "should_recommend": scored["should_recommend"],
                "reasons": reasons,
                "matched_skills": matched_skills,
                "missing_skills": missing_skills,
                "role_relevance": match.get("role_match", 0),
                "location_relevance": match.get("location_match", 0),
                "experience_relevance": match.get("experience_match", 0),
                "india_score": _india_first_score(job),
                "freshness": match.get("freshness", 0),
            })

        # Sort: source-aware final rank (candidate match + bounded source
        # quality bonus), then india_score DESC, freshness DESC.
        results.sort(
            key=lambda r: (
                combined_rank_score(r["recommendation_score"], r.get("job")),
                r["india_score"],
                r["freshness"],
            ),
            reverse=True,
        )

        if limit is not None:
            results = results[:limit]

        return results

    def _compute_skill_overlap(self, job: NormalizedJob, profile: Optional[UserProfile]) -> tuple[list[str], list[str]]:
        user_skills = [s.strip() for s in (profile.skills or []) if s and s.strip()] if profile else []
        job_skills = [s.strip() for s in (job.skills or []) if s and s.strip()]

        # Fallback: extract from description if job_skills empty
        if not job_skills and job.description:
            # Simple fallback: check user skills against description
            haystack = f"{job.title or ''} {job.description or ''}".lower()
            matched = [s for s in user_skills if s.lower() in haystack]
            missing = [s for s in user_skills if s.lower() not in haystack]
            return matched, missing

        if not user_skills:
            return [], job_skills

        # Normalize for comparison
        job_lower = [s.lower() for s in job_skills]
        matched: list[str] = []
        missing: list[str] = []
        for us in user_skills:
            if any(us.lower() in js for js in job_lower) or any(js in us.lower() for js in job_lower):
                matched.append(us)
            else:
                # Also check description haystack for partial
                haystack = f"{job.title or ''} {job.description or ''}".lower()
                if us.lower() in haystack:
                    matched.append(us)
                else:
                    missing.append(us)
        return matched, missing

    @staticmethod
    def to_recommendation_record(
        ranked: dict[str, Any],
        user_id: str,
        resume_id: Optional[str],
        status: str = "NEW",
    ) -> dict[str, Any]:
        """Convert a ranked dict to a recommendation-shaped dict for API output.

        Mirrors legacy RecommendationRecord + enriched fields.
        """
        job: NormalizedJob = ranked["job"]
        match = ranked["match"]
        # Build job payload similar to jobs API
        job_payload = {
            "id": ranked.get("job_id"),
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "description": job.description,
            "remote": job.remote,
            "role_category": job.role_category,
            "posted_at": job.posted_date,
            "url": job.apply_url or job.url,
            "skills": job.skills or [],
        }
        # Skill/keyword/semantic split: map from personalized
        skill_match = int(match.get("skill_match", 0))
        # keyword_match and semantic_similarity are not separately computed by personalized;
        # approximate via skill_match and role_match average for compatibility
        keyword_match = int((match.get("role_match", 0) * 0.5 + match.get("skill_match", 0) * 0.5))
        semantic_similarity = int(match.get("resume_match", 0) or skill_match)

        return {
            "id": ranked.get("job_id"),  # dynamic recommendations use job id as recommendation id
            "user_id": user_id,
            "job_id": ranked.get("job_id"),
            "resume_id": resume_id,
            "match_score": ranked["recommendation_score"],
            "skill_match": skill_match,
            "keyword_match": keyword_match,
            "semantic_similarity": semantic_similarity,
            "recommendation_reason": ranked["reasons"],
            "priority": ranked["priority"],
            "status": status,
            "created_at": job.posted_date,
            # Enriched explainability fields
            "recommendation_score": ranked["recommendation_score"],
            "level": ranked["level"],
            "reasons": ranked["reasons"],
            "matched_skills": ranked["matched_skills"],
            "missing_skills": ranked["missing_skills"],
            "role_relevance": ranked["role_relevance"],
            "location_relevance": ranked["location_relevance"],
            "experience_relevance": ranked["experience_relevance"],
            "match": match,
            "job": job_payload,
            # CamelCase aliases for frontend compatibility
            "jobId": ranked.get("job_id"),
            "resumeId": resume_id,
            "matchScore": ranked["recommendation_score"],
            "skillMatch": skill_match,
            "keywordMatch": keyword_match,
            "semanticSimilarity": semantic_similarity,
            "recommendationReason": ranked["reasons"],
        }
