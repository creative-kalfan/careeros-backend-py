"""Job relevance service: combines repository and personalized service."""

from __future__ import annotations

from typing import Optional

from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.repositories.job_repository import JobRepository
from app.repositories.profile_repository import ProfileRepository
from app.services.jobs.personalized_job_service import PersonalizedJobService

# India-indicative location tokens used for the India-first ranking boost.
# Matches city names, "India", "Remote - India", etc. so India-based roles
# rank higher without hiding global/remote roles entirely.
_INDIA_TOKENS = [
    "india",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "mumbai",
    "pune",
    "chennai",
    "delhi",
    "gurgaon",
    "gurugram",
    "noida",
    "kolkata",
    "ahmedabad",
    "kochi",
    "cochin",
    "indore",
    "jaipur",
    "chandigarh",
    "remote - india",
    "remote india",
]


def _india_first_score(job: NormalizedJob) -> int:
    """Return a 0-2 India-first ranking score for a job.

    2 = explicitly India-based location, 1 = remote (global/remote roles
    still rank above non-India on-site), 0 = non-India on-site.
    """
    location = (job.location or "").lower()
    if any(token in location for token in _INDIA_TOKENS):
        return 2
    if job.remote or "remote" in location:
        return 1
    return 0


class JobRelevanceService:
    """Combines repository and personalized service for job relevance."""

    def __init__(
        self,
        job_repository: Optional[JobRepository] = None,
        profile_repository: Optional[ProfileRepository] = None,
        personalized_service: Optional[PersonalizedJobService] = None,
    ) -> None:
        self.job_repository = job_repository or JobRepository()
        self.profile_repository = profile_repository or ProfileRepository()
        self.personalized_service = personalized_service or PersonalizedJobService()

    def get_relevant_jobs(
        self,
        user_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        role: Optional[str] = None,
        location: Optional[str] = None,
    ) -> tuple[list[NormalizedJob], int]:
        """Get jobs relevant to a user's profile.

        If no user_id is provided, returns all active jobs.
        """
        # Get the user's profile if available
        profile = self.profile_repository.get_profile(user_id) if user_id else None

        # Determine the role category filter (if desired_role is set)
        role_category = None
        if profile and profile.desired_role:
            from app.parsing.role_classifier import classify
            role_category = classify(profile.desired_role)
            if role_category == "Other":
                role_category = None

        # Get ALL matching jobs (no pagination at the DB layer) so the
        # Python-side sort (match score + India-first boost) can operate
        # across the full result set, not just one page. Pagination is
        # applied AFTER sorting. This ensures sources interleave naturally
        # instead of appearing grouped by ingestion batch.
        db_rows, total = self.job_repository.list_jobs(
            page=1,
            page_size=100000,
            role=role,
            location=location,
            role_category=role_category,
        )

        # Convert to NormalizedJob objects
        jobs = [NormalizedJob.model_validate(row) for row in db_rows]

        # If no profile, still apply India-first sort on the full set.
        if profile is None:
            # India-first without match scores: sort purely by india_score,
            # then recent first as a deterministic tiebreak.
            jobs.sort(
                key=lambda j: (_india_first_score(j),),
                reverse=True,
            )
            start = (page - 1) * page_size
            return jobs[start : start + page_size], total

        # Filter and calculate match scores
        filtered_jobs = self.personalized_service.filter_jobs(jobs, profile)
        for job in filtered_jobs:
            job.match = self.personalized_service.calculate_match_score(job, profile)

        # STRICT sort: match score descending FIRST, with india_first_score
        # as a tiebreaker/boost (not a separate hard grouping). Weak matches
        # sink to the bottom of the SAME list regardless of India tier.
        filtered_jobs.sort(
            key=lambda j: (
                j.match.get("overall", 0) if j.match else 0,
                _india_first_score(j),
            ),
            reverse=True,
        )

        # Paginate AFTER sorting.
        start = (page - 1) * page_size
        return filtered_jobs[start : start + page_size], total

    def get_job(self, job_id: str) -> Optional[NormalizedJob]:
        """Get a single job by id."""
        db_row = self.job_repository.get_job(job_id)
        if not db_row:
            return None
        return NormalizedJob.model_validate(db_row)