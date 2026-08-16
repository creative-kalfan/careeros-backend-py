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


class PersonalizedJobService:
    """Filters jobs based on user profile preferences."""

    def __init__(self) -> None:
        pass

    def filter_jobs(
        self,
        jobs: list[NormalizedJob],
        profile: Optional[UserProfile] = None,
    ) -> list[NormalizedJob]:
        """Filter jobs based on user profile preferences.

        If no profile is provided, returns all jobs.
        """
        if not profile:
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
        skill_match = self._score_skill_match(job, profile)
        resume_match = self._score_resume_match(job, profile)
        experience_match = self._score_experience_match(job, profile)
        location_match = self._score_location_match(job, profile)
        salary_match = self._score_salary_match(job, profile)
        company_preference = self._score_company_preference(job, profile)
        freshness = self._score_freshness(job)

        weights = {
            "role_match": 0.20,
            "skill_match": 0.20,
            "resume_match": 0.15,
            "experience_match": 0.10,
            "location_match": 0.15,
            "salary_match": 0.10,
            "company_preference": 0.05,
            "freshness": 0.05,
        }

        overall = (
            role_match * weights["role_match"]
            + skill_match * weights["skill_match"]
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
            "skill_match": round(skill_match),
            "resume_match": round(resume_match),
            "experience_match": round(experience_match),
            "location_match": round(location_match),
            "salary_match": round(salary_match),
            "company_preference": round(company_preference),
            "freshness": round(freshness),
        }

    def _score_role_match(self, job: NormalizedJob, profile: UserProfile) -> float:
        title = (job.title or "").lower()
        desired = (profile.desired_role or "").lower()
        if not desired:
            return 50.0

        # Normalize desired role.
        desired_canonical = normalize_role(desired)
        job_canonical = normalize_role(title)

        if desired_canonical and job_canonical:
            if desired_canonical == job_canonical:
                return 100.0

            if job_canonical in get_related_roles(desired_canonical):
                return 80.0

            if desired_canonical in get_related_roles(job_canonical):
                return 70.0

            # Same category via classifier.
            desired_category = classify(desired)
            job_category = classify(title)
            if desired_category == job_category and desired_category != "Other":
                return 75.0

        # Fallback: word overlap.
        desired_words = set(desired.split())
        title_words = set(re.findall(r"\w+", title))

        if desired in title:
            return 100.0

        overlap = len(desired_words & title_words)
        if overlap >= 2:
            return 80.0
        if overlap == 1:
            return 60.0

        category = (job.role_category or "").lower()
        if desired in category or category in desired:
            return 70.0

        return 30.0

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
        job_level = (job.experience_level or "").lower()
        title = (job.title or "").lower()

        if not user_exp and not job_level:
            # Fallback: infer seniority from job title keywords so the score
            # varies by job instead of collapsing to a single hardcoded default.
            senior_keywords = ["senior", "staff", "lead", "principal", "architect", "director"]
            junior_keywords = ["junior", "entry", "intern", "trainee", "graduate"]
            if any(k in title for k in senior_keywords):
                return 70.0
            if any(k in title for k in junior_keywords):
                return 40.0
            return 50.0

        experience_rank = {"intern": 0, "junior": 1, "entry": 1, "mid": 2, "senior": 3, "lead": 4, "principal": 5, "director": 6}
        job_rank = None
        for keyword, rank in experience_rank.items():
            if keyword in title or keyword in job_level:
                job_rank = rank
                break
        if job_rank is None:
            job_rank = 2

        user_rank = None
        for keyword, rank in experience_rank.items():
            if keyword in user_exp:
                user_rank = rank
                break
        if user_rank is None:
            user_rank = 2

        diff = abs(user_rank - job_rank)
        if diff == 0:
            return 100.0
        if diff == 1:
            return 70.0
        if diff == 2:
            return 40.0
        return 20.0

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
            india_keywords = ["bangalore", "bengaluru", "hyderabad", "mumbai", "pune", "chennai", "delhi", "gurgaon", "india"]
            if any(k in job_location for k in india_keywords):
                return 60.0
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
        company = (job.company or "").lower()
        for preferred in profile.preferred_companies:
            if preferred.lower() in company:
                return 100.0
        return 0.0

    def _score_freshness(self, job: NormalizedJob) -> float:
        if not job.posted_date:
            return 50.0
        try:
            posted = job.posted_date
            if isinstance(posted, str):
                from datetime import datetime
                posted_dt = datetime.fromisoformat(posted.replace("Z", "+00:00"))
                now = datetime.now(posted_dt.tzinfo)
                diff_days = (now - posted_dt).total_seconds() / 86400
                if diff_days <= 3:
                    return 100.0
                if diff_days <= 7:
                    return 85.0
                if diff_days <= 14:
                    return 70.0
                if diff_days <= 30:
                    return 50.0
                return 30.0
        except Exception:
            return 50.0
        return 50.0