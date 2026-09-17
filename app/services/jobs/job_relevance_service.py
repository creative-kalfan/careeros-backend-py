"""Job relevance service: combines repository and personalized service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.repositories.job_repository import JobRepository
from app.repositories.profile_repository import ProfileRepository
from app.services.jobs.personalized_job_service import PersonalizedJobService
from app.services.jobs.source_priority import combined_rank_score, source_quality_bonus

# India-indicative tokens for the India-first ranking boost. City list is the
# single source of truth in india_geography (task §1 high-value cities);
# "india" itself is matched on word boundaries so "Indiana, USA" never
# ranks as India. Ambiguous globals (Remote/Worldwide/APAC/...) score 1
# at most — never as India.
_BANGALORE_TOKENS = ["bengaluru", "bangalore"]

try:  # centralize the city list; fall back to the inline set if unavailable
    from app.services.jobs.india_geography import INDIAN_CITY_TOKENS as _CITY_TOKENS
    from app.services.jobs.india_geography import contains_india_marker as _contains_india
except Exception:  # pragma: no cover - import-time safety
    _CITY_TOKENS = (
        "bengaluru", "bangalore", "hyderabad", "mumbai", "pune", "chennai",
        "delhi", "gurgaon", "gurugram", "noida", "kolkata", "ahmedabad",
        "kochi", "cochin", "indore", "jaipur", "chandigarh",
    )

    def _contains_india(text: str) -> bool:  # type: ignore[misc]
        lowered = (text or "").lower()
        return "india" in lowered and "indiana" not in lowered or any(
            city in lowered for city in _CITY_TOKENS
        )


def _india_first_score(job: NormalizedJob) -> int:
    """Return a 0-3 India-first ranking score for a job.

    3 = Bangalore / Bengaluru (premier tech hub),
    2 = other explicitly India-based location (incl. multi-location with India),
    1 = generic remote/ambiguous (above foreign, below India),
    0 = foreign / unknown on-site. Ambiguous globals never score as India.
    """
    location = (job.location or "").lower()
    title = (job.title or "").lower()
    url = (job.url or "").lower()
    text = f"{location} {title} {url}"

    if any(token in text for token in _BANGALORE_TOKENS):
        return 3
    if _contains_india(text):
        return 2
    if job.remote or "remote" in text:
        return 1
    return 0


def _is_remote_job(job: NormalizedJob) -> bool:
    """One remote definition for every filter layer (flag OR location text).

    Crawlers derive the boolean flag from location text, but either signal
    can be missing (flag None with a "Remote" location, or flag True with a
    plain city location), so both count.
    """
    if job.remote is True:
        return True
    return "remote" in (job.location or "").lower()


def _recency_key(job: NormalizedJob) -> str:
    """Newest evidence wins: re-observation refreshes rank, posted_at untouched."""
    return max(
        job.posted_date or "",
        getattr(job, "last_seen_at", None) or "",
    )


def _get_job_seniority(job: NormalizedJob) -> str:
    """Classify seniority level from job attributes, title, and description."""
    lvl = (job.experience_level or "").lower().strip()
    if lvl:
        for key in ("entry", "fresher", "intern", "junior", "mid", "senior", "staff", "lead", "principal"):
            if key in lvl:
                return "entry" if key in ("entry", "fresher", "intern", "junior") else key
        return lvl

    try:
        from app.services.jobs.extraction_utils import (
            classify_seniority,
            extract_years_of_experience,
        )

        inferred, _ = classify_seniority(job.description or "", job.title or "")
        if inferred:
            inf = inferred.lower()
            return "entry" if inf in ("entry", "fresher", "intern", "junior") else inf

        years_min, _ = extract_years_of_experience(f"{job.title or ''} {job.description or ''}")
        if years_min is not None:
            if years_min <= 2:
                return "entry"
            if years_min < 5:
                return "mid"
            if years_min < 8:
                return "senior"
            return "staff"
    except Exception:
        pass
    return ""


def _is_entry_or_fresher(job: NormalizedJob) -> bool:
    """Check if job is entry-level, fresher, junior, or internship."""
    return _get_job_seniority(job) in ("entry", "fresher", "intern", "junior")


def _is_verified_active_mass_hiring(job: NormalizedJob) -> bool:
    """Check if job is verified active mass hiring."""
    return (
        getattr(job, "mass_hiring", None) == "VERIFIED_MASS_HIRING"
        and getattr(job, "mass_hiring_status", None) == "ACTIVE"
    )


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
            result = [j for j in result if _is_remote_job(j) == bool(remote)]

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
            # Frontend sends Entry/Mid/Senior/Staff+; normalize Staff+ -> staff.
            needle = experience.lower().strip().rstrip("+").strip()
            # Grouped levels: junior includes internships, staff includes
            # principal so level buckets behave like recruiters expect.
            # "fresher" (common India UI term) behaves as Entry.
            groups = {
                "intern": {"intern"},
                "entry": {"junior", "intern", "entry", "fresher"},
                "fresher": {"junior", "intern", "entry", "fresher"},
                "junior": {"junior", "intern", "entry"},
                "mid": {"mid", "middle"},
                "senior": {"senior"},
                "staff": {"staff", "principal", "lead"},
                "principal": {"staff", "principal", "lead"},
                "lead": {"staff", "principal", "lead"},
            }
            levels = groups.get(needle, {needle})
            result = [j for j in result if _get_job_seniority(j) in levels]

        return result

    @classmethod
    def _diversify_single_tier(cls, jobs: list[NormalizedJob]) -> list[NormalizedJob]:
        """Round-robin interleave by company within a single tier block."""
        groups: dict[str, list[NormalizedJob]] = {}
        order: list[str] = []
        for job in jobs:
            key = (job.company or "").strip().lower() or (
                f"\x00{job.external_job_id or job.id or job.title or ''}"
            ).lower()
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(job)
        out: list[NormalizedJob] = []
        round_idx = 0
        while len(out) < len(jobs):
            progressed = False
            for key in order:
                if round_idx < len(groups[key]):
                    out.append(groups[key][round_idx])
                    progressed = True
            round_idx += 1
            if not progressed:
                break
        return out

    @classmethod
    def _diversify_by_company(
        cls,
        jobs: list[NormalizedJob],
        tier_getter: Optional[Any] = None,
    ) -> list[NormalizedJob]:
        """Round-robin interleave by company over rank order.

        When tier_getter is provided, diversification operates tier-by-tier
        so company diversification never pushes high-priority opportunities
        below lower-tier or unrelated jobs.
        """
        if not jobs:
            return []
        if tier_getter is not None:
            from itertools import groupby
            out: list[NormalizedJob] = []
            for _, tier_group in groupby(jobs, key=tier_getter):
                out.extend(cls._diversify_single_tier(list(tier_group)))
            return out
        return cls._diversify_single_tier(jobs)

    @staticmethod
    def _sort_jobs(jobs: list[NormalizedJob], sort: Optional[str]) -> list[NormalizedJob]:
        """Dynamic sorting: newest / oldest / salary (default: relevance)."""
        if sort == "newest":
            jobs.sort(key=lambda j: (j.posted_date or "", j.external_job_id or "", j.title or ""), reverse=True)
        elif sort == "oldest":
            jobs.sort(key=lambda j: (j.posted_date or "", j.external_job_id or "", j.title or ""), reverse=False)
        elif sort == "salary":
            jobs.sort(key=lambda j: (j.salary_max or 0, j.external_job_id or ""), reverse=True)
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

        # Stage 1: Candidate retrieval. Match scoring is Python-side so the
        # full eligible set must be ranked — fetch past the PostgREST 1000-row
        # single-query cap via the repository's existing chunked path.
        # ponytail: O(eligible) Python rank; push-down impossible while the
        # score needs the user profile. Revisit only if eligible sets grow
        # past low-thousands and profiling blames this fetch.
        CANDIDATE_POOL_LIMIT = 1000
        # Experience is filtered Python-side only: the jobs.experience_level
        # column is never populated by crawlers (always NULL), so a DB eq
        # filter zeroes every result. _python_filter infers level instead.
        # Remote is likewise Python-side only: the DB matches location text
        # while _python_filter matches the flag-or-location single definition,
        # so a DB pre-filter silently drops flag-remote rows with plain city
        # locations (and vice versa).
        db_rows, db_total = self.job_repository.list_jobs(
            page=1,
            page_size=CANDIDATE_POOL_LIMIT,
            role=role,
            location=location,
            role_category=None,
            company=company,
            remote=None,
            employment_type=employment_type,
            experience=None,
            sort=sort,
        )
        if db_total > len(db_rows):
            db_rows, db_total = self.job_repository.list_jobs(
                page=1,
                page_size=db_total,
                role=role,
                location=location,
                role_category=None,
                company=company,
                remote=None,
                employment_type=employment_type,
                experience=None,
                sort=sort,
            )

        # Convert to NormalizedJob objects
        jobs = [NormalizedJob.model_validate(row) for row in db_rows]

        # Python-side filtering (idempotent with the DB filters; also covers
        # repositories that do not implement the extended filters).
        jobs = self._python_filter(
            jobs, company, skills, remote, employment_type, experience
        )

        has_python_filter = bool(company or skills or remote is not None or employment_type or experience)

        # Stage 0 Opportunity Tier / Fresher / Mass-Hiring helpers
        def _job_tier(j: NormalizedJob, match_score: float = 0.0) -> int:
            """Opportunity ranking tier (higher integer = better tier):
            Tier 4: High-priority opportunity:
                    - Highly relevant fresh entry/fresher (posted <= 7d, match >= 50 or unauth)
                    - OR Active verified mass-hiring with strong relevance (match >= 60 or unauth)
            Tier 3: Active entry/fresher opportunity (match >= 45 or unauth)
                    - OR Active verified mass-hiring with acceptable relevance (match >= 45)
            Tier 2: Fresh relevant mid-level (match >= 45 or unauth fresh)
            Tier 1: Older ordinary relevant (match >= 40 or unauth)
            Tier 0: Weakly relevant / role mismatch (match < 40) or expired campaign
            """
            is_active_mass = _is_verified_active_mass_hiring(j)
            is_expired_mass = getattr(j, "mass_hiring_status", None) == "EXPIRED"
            if is_expired_mass:
                return 0 if (match_score > 0 and match_score < 50.0) else 1

            is_entry = _is_entry_or_fresher(j)
            rec = _recency_key(j)
            is_fresh = False
            if rec:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(rec.replace("Z", "+00:00"))
                    now = datetime.now(dt.tzinfo or timezone.utc)
                    is_fresh = (now - dt).total_seconds() / 86400 <= 7.0
                except Exception:
                    is_fresh = False

            # Semantic relevance checks (0.0 means unauthenticated feed)
            is_strong = (match_score >= 60.0 or match_score == 0.0)
            is_acceptable = (match_score >= 45.0 or match_score == 0.0)

            # Mass hiring requires acceptable relevance; does not elevate unrelated jobs
            if is_active_mass and is_strong:
                return 4
            if is_entry and is_fresh and is_acceptable:
                return 4
            if is_active_mass and is_acceptable:
                return 3
            if is_entry and is_acceptable:
                return 3
            if is_fresh and is_acceptable:
                return 2
            if match_score >= 40.0 or match_score == 0.0:
                return 1
            return 0

        # If no profile, apply India-first + Fresher-first opportunity ordering.
        if profile is None:
            total = len(jobs) if has_python_filter else db_total
            if sort in ("newest", "oldest", "salary"):
                self._sort_jobs(jobs, sort)
            else:
                # Opportunity ranking: Tier first, India-first, source quality, recency.
                # Fresher/entry gets intentional default advantage.
                def _unauth_rank_key(j: NormalizedJob) -> tuple:
                    tier = _job_tier(j, match_score=0.0)
                    fresher_bonus = 10.0 if _is_entry_or_fresher(j) else 0.0
                    is_active_mass = _is_verified_active_mass_hiring(j)
                    mass_bonus = 6.0 if is_active_mass else 0.0
                    ind = _india_first_score(j)
                    score = fresher_bonus + mass_bonus + source_quality_bonus(j)
                    return (
                        tier,
                        score,
                        ind,
                        _recency_key(j),
                        j.external_job_id or "",
                    )

                jobs.sort(key=_unauth_rank_key, reverse=True)
                jobs = self._diversify_by_company(jobs, tier_getter=lambda j: _job_tier(j, 0.0))
            start = (page - 1) * page_size
            return jobs[start : start + page_size], total

        # Stage 1 Candidate Retrieval: broad candidate pool, not strictly filtered by role category
        try:
            filtered_jobs = self.personalized_service.filter_jobs(jobs, profile, strict=False)
        except TypeError:
            filtered_jobs = self.personalized_service.filter_jobs(jobs, profile)
        for job in filtered_jobs:
            job.match = self.personalized_service.calculate_match_score(job, profile)

        total = len(filtered_jobs) if has_python_filter else db_total

        if sort in ("newest", "oldest", "salary"):
            self._sort_jobs(filtered_jobs, sort)
        else:
            # Stage 2 Ranking:
            # Tiered opportunity rank + match score + Fresher advantage + bounded Mass Hiring + India boost.
            def _rank_key(j: NormalizedJob) -> tuple:
                match_overall = j.match.get("overall", 0) if j.match else 0
                tier = _job_tier(j, match_score=match_overall)
                fresher_bonus = 8.0 if _is_entry_or_fresher(j) else 0.0

                # Bounded mass hiring priority modifier only if active and sufficiently relevant
                is_active_mass = _is_verified_active_mass_hiring(j)
                mass_bonus = 6.0 if (is_active_mass and match_overall >= 45.0) else 0.0

                ind = _india_first_score(j)
                ind_boost = {3: 6.0, 2: 4.0, 1: 2.0, 0: 0.0}.get(ind, 0.0)
                score = combined_rank_score(match_overall, j) + fresher_bonus + mass_bonus + ind_boost
                return (
                    tier,
                    score,
                    ind,
                    _recency_key(j),
                    j.external_job_id or "",
                )

            filtered_jobs.sort(key=_rank_key, reverse=True)
            filtered_jobs = self._diversify_by_company(
                filtered_jobs,
                tier_getter=lambda j: _job_tier(j, match_score=j.match.get("overall", 0) if j.match else 0),
            )

        # Paginate AFTER sorting/diversification.
        start = (page - 1) * page_size
        return filtered_jobs[start : start + page_size], total

    def get_job(self, job_id: str) -> Optional[NormalizedJob]:
        """Get a single job by id."""
        db_row = self.job_repository.get_job(job_id)
        if not db_row:
            return None
        return NormalizedJob.model_validate(db_row)

    @staticmethod
    def normalize_match_payload(job_data: dict) -> dict:
        """Normalize a frontend match payload accepting camelCase + snake_case.

        The Jobs page historically sends ``{title, companyName}`` while the
        canonical model uses ``company``. Map known aliases so company and
        other fields are not silently dropped by validation.
        """
        data = dict(job_data or {})
        if data.get("company") is None:
            alias = data.get("companyName") or data.get("company_name")
            if alias:
                data["company"] = alias
        if data.get("title") is None and data.get("role"):
            data["title"] = data.get("role")
        if data.get("description") is None and data.get("overview"):
            data["description"] = data.get("overview")
        if data.get("skills") is None and isinstance(data.get("techStack"), list):
            data["skills"] = data.get("techStack")
        apply_url = data.get("applyUrl") or data.get("url")
        if data.get("apply_url") is None and apply_url:
            data["apply_url"] = apply_url
        posted = data.get("postedDate") or data.get("posted_date") or data.get("postedAt")
        if data.get("posted_date") is None and posted:
            data["posted_date"] = posted
        return data

    @staticmethod
    def missing_skills_for(job: NormalizedJob, profile: Optional[UserProfile]) -> list[str]:
        """Skills present on the job but absent from the user profile."""
        job_skills = [s for s in (job.skills or []) if s]
        if not job_skills:
            return []
        user_skills = {s.lower() for s in ((profile.skills if profile else []) or []) if s}
        if not user_skills:
            return list(job_skills)
        return [s for s in job_skills if s.lower() not in user_skills]

    def match_job_for_user(
        self,
        user_id: Optional[str],
        job_id: Optional[str] = None,
        job_data: Optional[dict] = None,
        resume_text: Optional[str] = None,
    ) -> tuple[NormalizedJob, dict]:
        """Resolve the job + profile and score with the canonical 8-factor engine.

        - Job resolution prefers the DB row by ``job_id`` (full
          description/skills) so re-analyze scores the real posting, falling
          back to the normalized client payload when the id is unknown.
        - Profile resolution uses the stored user profile. ``resume_text`` is
          accepted for contract compatibility but is not required: the
          authenticated user's profile is the source of truth for scoring.
        """
        job: Optional[NormalizedJob] = None
        if job_id:
            try:
                job = self.get_job(job_id)
            except Exception:
                job = None
        if job is None and job_data:
            normalized = self.normalize_match_payload(job_data)
            # ``id`` inside the nested job object is also a lookup key.
            nested_id = normalized.get("id") or normalized.get("jobId")
            if nested_id:
                try:
                    job = self.get_job(str(nested_id))
                except Exception:
                    job = None
            if job is None:
                job = NormalizedJob.model_validate(normalized)
        if job is None:
            raise ValueError("job_not_found")

        profile: Optional[UserProfile] = None
        if user_id:
            try:
                profile = self.profile_repository.get_profile(user_id)
            except Exception:
                profile = None
        if profile is None:
            # No stored profile: fall back to an empty profile so the
            # deterministic engine still returns varied, job-dependent
            # fallback scores instead of all zeros. resume_text is not
            # parsed into a new algorithm — scoring stays canonical.
            profile = UserProfile()

        match = self.personalized_service.calculate_match_score(job, profile)
        missing = self.missing_skills_for(job, profile)
        if missing:
            match["missing_skills"] = missing
            match["missingSkills"] = missing
        else:
            match.setdefault("missing_skills", [])
            match.setdefault("missingSkills", [])
        # camelCase aliases so the existing frontend JobMatchResponse readers
        # (matchScore/skillMatchScore/...) display the fresh result instead of
        # silently falling back to the stale list score.
        match.setdefault("matchScore", match.get("overall", 0))
        match.setdefault("overall", match.get("matchScore", 0))
        match.setdefault("skillMatchScore", match.get("skill_match", 0))
        match.setdefault("skill_match", match.get("skillMatchScore", 0))
        match.setdefault("keywordMatchScore", match.get("resume_match", 0))
        match.setdefault("semanticSimilarityScore", match.get("resume_match", 0))
        match.setdefault("missingKeywords", [])
        match.setdefault("recommendations", [])
        match.setdefault("experienceMatch", match.get("experience_match", 0))
        match.setdefault("locationMatch", match.get("location_match", 0))
        match.setdefault("salaryMatch", match.get("salary_match", 0))
        match.setdefault("companyPreference", match.get("company_preference", 0))
        return job, match