"""Personalized job service: user-specific job filtering and ranking."""

from __future__ import annotations

import re
from typing import Optional

from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.parsing.role_classifier import classify
from app.parsing.role_taxonomy import (
    get_category_for_role,
    get_related_roles,
    normalize_role,
)

_GENERIC_ROLE_WORDS = {
    "engineer", "engineering", "developer", "development", "dev",
    "analyst", "analytics", "specialist", "consultant", "associate",
    "lead", "senior", "junior", "staff", "principal", "intern", "internship",
    "trainee", "entry", "level", "manager", "management", "director",
    "officer", "executive", "team", "head", "vp", "ii", "iii", "iv", "v",
    "sr", "jr", "expert",
}


class PersonalizedJobService:
    """Filters jobs based on user profile preferences."""

    def __init__(self) -> None:
        pass

    def filter_jobs(
        self,
        jobs: list[NormalizedJob],
        profile: Optional[UserProfile] = None,
        strict: bool = True,
    ) -> list[NormalizedJob]:
        """Filter jobs based on user profile preferences.

        If no profile is provided or strict is False, returns all jobs.
        When strict=True, filters strictly by primary category and related canonical roles.
        """
        if not profile or not strict:
            return jobs

        if not profile.desired_role:
            return jobs

        # Normalize desired role to canonical form.
        canonical = normalize_role(profile.desired_role)
        if not canonical:
            return jobs

        # Primary category for exact filter.
        primary_category = get_category_for_role(canonical)
        if not primary_category:
            return jobs

        # Related roles for controlled expansion.
        related_roles = get_related_roles(canonical)

        filtered: list[NormalizedJob] = []
        for job in jobs:
            if job.role_category == primary_category:
                filtered.append(job)
                continue

            # Include jobs whose title maps to a related canonical role.
            job_canonical = normalize_role(job.title)
            if job_canonical and job_canonical in related_roles:
                filtered.append(job)

        return filtered

    def calculate_match_score(
        self,
        job: NormalizedJob,
        profile: Optional[UserProfile] = None,
    ) -> dict[str, float]:
        """Calculate a match score for a job based on user profile.

        Returns a dictionary of match scores (0-100) for different criteria.
        """
        if not profile:
            return {
                "overall": 0,
                "role_match": 0,
                "skill_match": 0,
                "resume_match": 0,
                "experience_match": 0,
                "location_match": 0,
                "salary_match": 0,
                "company_preference": 0,
                "freshness": 0,
            }

        role_match = self._score_role_match(job, profile)
        raw_skill_match = self._score_skill_match(job, profile)
        resume_match = self._score_resume_match(job, profile)
        experience_match = self._score_experience_match(job, profile)
        location_match = self._score_location_match(job, profile)
        salary_match = self._score_salary_match(job, profile)
        company_preference = self._score_company_preference(job, profile)
        freshness = self._score_freshness(job)

        # Gate skill match contribution when role compatibility is poor.
        # If role_match < 40.0, skill match cannot compensate for role mismatch.
        if role_match < 40.0:
            effective_skill_match = raw_skill_match * max(0.05, (role_match / 40.0) * 0.3)
        else:
            effective_skill_match = raw_skill_match

        weights = {
            "role_match": 0.30,
            "skill_match": 0.20,
            "resume_match": 0.10,
            "experience_match": 0.15,
            "location_match": 0.10,
            "salary_match": 0.05,
            "company_preference": 0.05,
            "freshness": 0.05,
        }

        overall = (
            role_match * weights["role_match"]
            + effective_skill_match * weights["skill_match"]
            + resume_match * weights["resume_match"]
            + experience_match * weights["experience_match"]
            + location_match * weights["location_match"]
            + salary_match * weights["salary_match"]
            + company_preference * weights["company_preference"]
            + freshness * weights["freshness"]
        )

        return {
            "overall": round(overall),
            "role_match": round(role_match),
            "skill_match": round(effective_skill_match),
            "resume_match": round(resume_match),
            "experience_match": round(experience_match),
            "location_match": round(location_match),
            "salary_match": round(salary_match),
            "company_preference": round(company_preference),
            "freshness": round(freshness),
        }

    def _score_role_match(self, job: NormalizedJob, profile: UserProfile) -> float:
        title = (job.title or "").lower().strip()
        desired = (profile.desired_role or "").lower().strip()
        if not desired:
            return 50.0

        # Exact substring match (e.g., "data analyst" in "senior data analyst")
        if desired in title:
            return 100.0

        desired_canonical = normalize_role(desired)
        job_canonical = normalize_role(title)

        if desired_canonical and job_canonical:
            if desired_canonical == job_canonical:
                if desired in title or title in desired:
                    return 100.0
                return 85.0

            # Direct taxonomy relationship check
            desired_related = get_related_roles(desired_canonical)
            job_related = get_related_roles(job_canonical)

            if job_canonical in desired_related or desired_canonical in job_related:
                desired_canon_lower = desired_canonical.lower()
                job_canon_lower = job_canonical.lower()

                # Shared role noun / anchor? (e.g. both are analyst, or both are developer)
                shared_nouns = {"analyst", "developer", "engineer", "designer", "manager"}
                both_share_noun = any(
                    noun in desired_canon_lower and noun in job_canon_lower
                    for noun in shared_nouns
                )
                if both_share_noun:
                    return 85.0
                return 70.0

            # Same broad category via classifier or taxonomy lookup
            desired_category = get_category_for_role(desired_canonical) or classify(desired)
            job_category = get_category_for_role(job_canonical) or classify(title)
            if desired_category and job_category and desired_category == job_category and desired_category != "Other":
                # Only award 65 if there is semantic token overlap between the roles
                # (e.g. "data" in Data Analyst vs Data Engineer).
                # Distant sub-disciplines with 0 overlap (e.g. Frontend vs DevOps)
                # within giant umbrella categories (like "Software Engineering") are distinct.
                desired_tokens_cat = {w for w in re.findall(r"\w+", desired) if w not in _GENERIC_ROLE_WORDS and len(w) > 2}
                title_tokens_cat = {w for w in re.findall(r"\w+", title) if w not in _GENERIC_ROLE_WORDS and len(w) > 2}
                if desired_tokens_cat & title_tokens_cat:
                    return 65.0
                return 15.0

        # Non-canonical / fallback matching
        # Filter out generic role stop words so "Software Engineering Senior Analyst"
        # doesn't match "Data Analyst" just because both have "analyst"
        desired_tokens = {w for w in re.findall(r"\w+", desired) if w not in _GENERIC_ROLE_WORDS and len(w) > 2}
        title_tokens = {w for w in re.findall(r"\w+", title) if w not in _GENERIC_ROLE_WORDS and len(w) > 2}

        if desired_tokens and title_tokens:
            overlap = desired_tokens & title_tokens
            if len(overlap) >= 2:
                return 75.0
            if len(overlap) == 1:
                desired_cat = classify(desired)
                job_cat = classify(title)
                if desired_cat == job_cat and desired_cat != "Other":
                    return 65.0
                return 40.0

        category = (job.role_category or "").lower()
        if category:
            desired_cat = (classify(desired) or "").lower()
            if desired in category or (desired_cat and desired_cat in category):
                return 50.0

        # Truly unrelated role family (e.g. Data Analyst vs Software Engineer)
        return 5.0

    def _score_skill_match(self, job: NormalizedJob, profile: UserProfile) -> float:
        user_skills = [s.lower() for s in (profile.skills or []) if s]
        job_skills = [s.lower() for s in (job.skills or []) if s]

        if not user_skills:
            # Fallback: score based on how many common tech skills appear in the job
            # content so the score varies by job instead of collapsing to a single
            # hardcoded default.
            common_skills = [
                "python", "javascript", "typescript", "react", "node", "java",
                "sql", "postgresql", "aws", "docker", "kubernetes", "git",
                "agile", "rest", "api", "cloud", "ci/cd", "testing", "security",
                "data", "machine learning", "golang", "rust", "graphql",
            ]
            haystack = f"{job.title or ''} {job.description or ''}".lower()
            matched = sum(1 for s in common_skills if s in haystack)
            return min(100.0, (matched / len(common_skills)) * 100.0)
        if not job_skills:
            # Most jobs from ATS/aggregator sources don't have an extracted
            # skills list in the DB (only in the raw description). Fall back
            # to scanning the title + description text for the user's skills
            # so scores genuinely vary by job content rather than collapsing
            # to the same 30 default.
            haystack = f"{job.title or ''} {job.description or ''}".lower()
            matched = sum(1 for s in user_skills if s in haystack)
            return min(100.0, (matched / len(user_skills)) * 100.0)

        matched = sum(1 for s in user_skills if any(s in js for js in job_skills))
        return min(100.0, (matched / len(user_skills)) * 100.0)

    def _score_resume_match(self, job: NormalizedJob, profile: UserProfile) -> float:
        title = (job.title or "").lower()
        desired = (profile.desired_role or "").lower()
        if not desired:
            return 0.0
        return 100.0 if desired in title else 0.0

    def _score_experience_match(self, job: NormalizedJob, profile: UserProfile) -> float:
        user_exp = (profile.experience or "").lower()
        user_role = (profile.current_role or "").lower()
        job_level = (job.experience_level or "").lower()
        title = (job.title or "").lower()

        experience_rank = {
            "intern": 0, "internship": 0, "trainee": 0, "fresher": 0, "graduate": 0,
            "junior": 1, "entry": 1, "entry-level": 1, "associate": 1,
            "mid": 2, "mid-level": 2, "intermediate": 2,
            "senior": 3, "sr": 3, "sr.": 3,
            "staff": 4, "lead": 4, "team lead": 4,
            "principal": 5, "director": 6, "head": 6, "vp": 7,
        }

        def _extract_rank(text: str) -> Optional[int]:
            if not text:
                return None
            for kw, r in experience_rank.items():
                if re.search(rf"\b{re.escape(kw)}\b", text):
                    return r
            m = re.search(r"(\d+)\s*(?:\+|-\d+)?\s*(?:year|yr)", text)
            if m:
                years = int(m.group(1))
                if years <= 1:
                    return 1
                elif years <= 4:
                    return 2
                elif years <= 7:
                    return 3
                elif years <= 10:
                    return 4
                else:
                    return 5
            return None

        job_rank = _extract_rank(job_level)
        if job_rank is None:
            job_rank = _extract_rank(title)
        if job_rank is None:
            job_rank = 2

        user_rank = _extract_rank(user_exp)
        if user_rank is None:
            user_rank = _extract_rank(user_role)
        if user_rank is None:
            user_rank = 2

        diff = abs(user_rank - job_rank)
        if diff == 0:
            return 100.0
        if diff == 1:
            return 75.0
        if diff == 2:
            return 40.0
        return 15.0

    def _score_location_match(self, job: NormalizedJob, profile: UserProfile) -> float:
        user_location = (profile.location or "").lower().strip()
        preferred_locations = [loc.lower().strip() for loc in (profile.preferred_locations or []) if loc]
        job_location = (job.location or "").lower().strip()
        remote_pref = (profile.remote_preference or "any").lower()
        is_remote = bool(job.remote)

        if remote_pref == "remote" and is_remote:
            return 100.0
        if remote_pref == "onsite" and is_remote:
            return 20.0
        if remote_pref == "hybrid" and is_remote:
            return 70.0

        if not job_location:
            return 50.0

        if user_location and (user_location in job_location or job_location in user_location):
            return 100.0

        for pref in preferred_locations:
            if pref in job_location or job_location in pref:
                return 100.0
            if self._fuzzy_location_match(pref, job_location):
                return 80.0

        if not user_location and not preferred_locations:
            # No user location preference set: score based on job location
            # quality so the score varies by job instead of collapsing to 0.
            if is_remote:
                return 80.0
            if any(k in job_location for k in ("bangalore", "bengaluru")):
                return 80.0
            india_keywords = ["hyderabad", "mumbai", "pune", "chennai", "delhi", "gurgaon", "gurugram", "noida", "kolkata", "india"]
            if any(k in job_location for k in india_keywords):
                return 65.0
            return 40.0

        if is_remote:
            return 60.0

        return 0.0

    def _fuzzy_location_match(self, user_loc: str, job_loc: str) -> bool:
        user_parts = set(re.findall(r"\w+", user_loc.lower()))
        job_parts = set(re.findall(r"\w+", job_loc.lower()))
        if not user_parts or not job_parts:
            return False
        overlap = len(user_parts & job_parts)
        return overlap >= 1 and overlap / len(user_parts | job_parts) >= 0.4

    def _score_salary_match(self, job: NormalizedJob, profile: UserProfile) -> float:
        if not job.salary and job.salary_min is None and job.salary_max is None:
            return 50.0
        if not profile.salary_expectation_min and not profile.salary_expectation_max:
            # No user salary expectation set: score based on salary transparency
            # so the score varies by job instead of collapsing to a single default.
            if job.salary_min is not None and job.salary_max is not None:
                return 70.0
            return 30.0

        salary_min = job.salary_min
        salary_max = job.salary_max

        if salary_min is None or salary_max is None:
            return 50.0

        user_min = profile.salary_expectation_min or 0
        user_max = profile.salary_expectation_max or float("inf")

        if salary_max < user_min:
            return 20.0
        if salary_min > user_max:
            return 30.0
        overlap_min = max(salary_min, user_min)
        overlap_max = min(salary_max, user_max)
        if overlap_max >= overlap_min:
            return 100.0
        return 50.0

    def _score_company_preference(self, job: NormalizedJob, profile: UserProfile) -> float:
        if not profile.preferred_companies:
            return 50.0
        from app.services.jobs.job_service import normalize_company_name

        company = (normalize_company_name(job.company) or "").lower()
        for preferred in profile.preferred_companies:
            if (normalize_company_name(preferred) or "").lower() in company:
                return 100.0
        return 0.0

    def _score_freshness(self, job: NormalizedJob) -> float:
        # Active mass-hiring override: an actively hiring mass-hiring campaign
        # retains fresh priority even if the posting is older.
        is_active_mass_hiring = (
            getattr(job, "mass_hiring", None) == "VERIFIED_MASS_HIRING"
            and getattr(job, "mass_hiring_status", None) == "ACTIVE"
        )
        if is_active_mass_hiring:
            return 95.0

        # Expired mass-hiring loses special boost:
        if getattr(job, "mass_hiring_status", None) == "EXPIRED":
            return 20.0

        # Observation-aware: re-observed jobs regain freshness without
        # rewriting posted_date. Score = max(posting age, observation age).
        posted_score = self._freshness_from_iso(job.posted_date)
        observed_iso = getattr(job, "last_seen_at", None)
        if observed_iso:
            return max(posted_score, self._freshness_from_iso(observed_iso))
        return posted_score

    @staticmethod
    def _freshness_from_iso(value: object) -> float:
        if not value:
            return 40.0
        try:
            posted = value
            if isinstance(posted, str):
                from datetime import datetime
                posted_dt = datetime.fromisoformat(posted.replace("Z", "+00:00"))
                now = datetime.now(posted_dt.tzinfo)
                diff_days = (now - posted_dt).total_seconds() / 86400
                if diff_days <= 1:
                    return 100.0
                if diff_days <= 7:
                    return 85.0
                if diff_days <= 14:
                    return 60.0
                if diff_days <= 30:
                    return 35.0
                return 15.0
        except Exception:
            return 40.0
        return 40.0