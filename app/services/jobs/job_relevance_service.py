"""Job relevance service: combines repository and personalized service."""

from __future__ import annotations

from typing import Optional

from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.repositories.job_repository import JobRepository
from app.repositories.profile_repository import ProfileRepository
from app.services.jobs.personalized_job_service import PersonalizedJobService
from app.services.jobs.source_priority import combined_rank_score

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

    @staticmethod
    def _python_filter(
        jobs: list[NormalizedJob],
        company: Optional[str],
        skills: Optional[list[str] | str],
        remote: Optional[bool],
        employment_type: Optional[str],
        experience: Optional[str],
    ) -> list[NormalizedJob]:
        """Python-side multi-parameter filtering (source-agnostic)."""
        result = jobs

        if company:
            needle = company.lower()
            result = [j for j in result if j.company and needle in j.company.lower()]

        if remote is not None:
            result = [j for j in result if bool(j.remote) == bool(remote)]

        if skills:
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.split(",") if s.strip()]
            wanted = [s.lower() for s in skills if s]
            if wanted:

                def _has_skill(job: NormalizedJob) -> bool:
                    haystack = " ".join(job.skills or []).lower()
                    if not haystack:
                        haystack = (job.description or "").lower()
                    return any(s in haystack for s in wanted)

                result = [j for j in result if _has_skill(j)]

        if employment_type:
            needle = employment_type.lower()
            result = [
                j for j in result
                if j.employment_type and needle in j.employment_type.lower()
            ]

        if experience:
            needle = experience.lower()
            # Grouped levels: junior includes internships, staff includes
            # principal so level buckets behave like recruiters expect.
            groups = {
                "intern": {"intern"},
                "junior": {"junior", "intern", "entry"},
                "mid": {"mid", "middle"},
                "senior": {"senior"},
                "staff": {"staff", "principal", "lead"},
            }
            levels = groups.get(needle, {needle})
            result = [
                j for j in result
                if j.experience_level and j.experience_level.lower() in levels
            ]

        return result

    @staticmethod
    def _sort_jobs(jobs: list[NormalizedJob], sort: Optional[str]) -> list[NormalizedJob]:
        """Dynamic sorting: newest / oldest / salary (default: relevance)."""
        if sort == "newest":
            jobs.sort(key=lambda j: j.posted_date or "", reverse=True)
        elif sort == "oldest":
            jobs.sort(key=lambda j: j.posted_date or "", reverse=False)
        elif sort == "salary":
            jobs.sort(key=lambda j: j.salary_max or 0, reverse=True)
        return jobs

    def get_relevant_jobs(
        self,
        user_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        role: Optional[str] = None,
        location: Optional[str] = None,
        company: Optional[str] = None,
        skills: Optional[list[str] | str] = None,
        remote: Optional[bool] = None,
        employment_type: Optional[str] = None,
        experience: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> tuple[list[NormalizedJob], int]:
        """Get jobs relevant to a user's profile.

        If no user_id is provided, returns all active jobs. Supports
        multi-parameter filtering and dynamic sorting with pagination applied
        over the fully filtered set.
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
        # Python-side sort (match score + source-quality + India-first boost)
        # can operate across the full result set. Pagination is applied AFTER
        # sorting/filtering.
        db_rows, _total = self.job_repository.list_jobs(
            page=1,
            page_size=100000,
            role=role,
            location=location,
            role_category=role_category,
            company=company,
            remote=remote,
            employment_type=employment_type,
            experience=experience,
            sort=sort,
        )

        # Convert to NormalizedJob objects
        jobs = [NormalizedJob.model_validate(row) for row in db_rows]

        # Python-side filtering (idempotent with the DB filters; also covers
        # repositories that do not implement the extended filters).
        jobs = self._python_filter(
            jobs, company, skills, remote, employment_type, experience
        )
        total = len(jobs)

        # If no profile, apply India-first / dynamic ordering.
        if profile is None:
            if sort in ("newest", "oldest", "salary"):
                self._sort_jobs(jobs, sort)
            else:
                # India-first without match scores; recent first as a
                # deterministic tiebreak.
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

        if sort in ("newest", "oldest", "salary"):
            self._sort_jobs(filtered_jobs, sort)
        else:
            # STRICT sort: candidate match + bounded source-quality bonus
            # first (official company career postings get a small deliberate
            # boost, see source_priority), with india_first_score as a
            # tiebreaker/boost. Weak matches still sink in the SAME list.
            filtered_jobs.sort(
                key=lambda j: (
                    combined_rank_score(j.match.get("overall", 0) if j.match else 0, j),
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