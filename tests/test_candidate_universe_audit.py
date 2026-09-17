"""Regression tests auditing candidate universe preservation, pagination correctness,
fresher/entry inclusion, and active verified mass-hiring inclusion outside the initial DB window."""

from datetime import datetime, timezone, timedelta
import pytest

from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.services.jobs.job_relevance_service import JobRelevanceService
from app.services.jobs.personalized_job_service import PersonalizedJobService


class MockAuditedJobRepository:
    """Mock repository with a large dataset (e.g. 1500 jobs) supporting targeted priority retrieval."""

    def __init__(self, all_jobs: list[NormalizedJob]):
        self.all_jobs = all_jobs

    def list_jobs(self, page: int = 1, page_size: int = 1000, **kwargs):
        start = (page - 1) * page_size
        rows = [j.model_dump() for j in self.all_jobs[start : start + page_size]]
        return rows, len(self.all_jobs)

    def get_priority_candidates(
        self,
        role=None,
        location=None,
        company=None,
        employment_type=None,
        desired_role=None,
        limit_per_category=500,
    ):
        mass = [
            j.model_dump()
            for j in self.all_jobs
            if getattr(j, "mass_hiring", None) == "VERIFIED_MASS_HIRING"
            and getattr(j, "mass_hiring_status", None) == "ACTIVE"
        ]
        freshers = [
            j.model_dump()
            for j in self.all_jobs
            if any(
                w in (j.title or "").lower()
                for w in ("intern", "fresher", "junior", "trainee", "entry", "associate")
            )
            or (j.experience_level and j.experience_level.lower() in ("entry", "fresher", "intern"))
        ]
        target = (role or desired_role or "").lower()
        role_matched = [
            j.model_dump()
            for j in self.all_jobs
            if target and target in (j.title or "").lower()
        ]
        seen = set()
        out = []
        for r in mass + freshers + role_matched:
            k = r.get("external_job_id") or r.get("id")
            if k and k not in seen:
                seen.add(k)
                out.append(r)
        return out


def test_outside_window_fresher_job_surfaces_for_entry_candidate():
    """Verify that a highly relevant fresher job outside the first 1000 DB rows
    enters candidate consideration and is prioritized for an entry candidate."""
    now_iso = datetime.now(timezone.utc).isoformat()
    old_iso = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()

    jobs = [
        NormalizedJob(
            id=f"senior-{i}",
            external_job_id=f"senior-{i}",
            title=f"Senior Staff Architect {i}",
            company=f"BigCorp {i % 20}",
            location="Bengaluru, India",
            skills=["python", "system design"],
            experience_level="Senior",
            posted_date=now_iso,
        )
        for i in range(1000)
    ]

    outside_fresher = NormalizedJob(
        id="fresher-target",
        external_job_id="fresher-target",
        title="Junior Python Developer",
        company="StartupX",
        location="Bengaluru, India",
        skills=["python", "fastapi"],
        experience_level="Entry",
        posted_date=old_iso,
    )
    jobs.append(outside_fresher)

    repo = MockAuditedJobRepository(jobs)
    profile = UserProfile(
        id="entry-user",
        desired_role="Python Developer",
        experience="Fresher",
        skills=["python", "fastapi"],
        preferred_locations=["Bengaluru"],
    )
    mock_prof_repo = type("MockProf", (), {"get_profile": lambda s, uid: profile})()

    service = JobRelevanceService(
        job_repository=repo,
        profile_repository=mock_prof_repo,
        personalized_service=PersonalizedJobService(),
    )

    ranked_page1, total = service.get_relevant_jobs(user_id="entry-user", page=1, page_size=20)

    assert total == 1001
    top_ids = [j.external_job_id for j in ranked_page1]
    assert outside_fresher.external_job_id in top_ids, "Outside-the-1000 fresher must surface on page 1"
    assert ranked_page1[0].external_job_id == outside_fresher.external_job_id


def test_outside_window_mass_hiring_job_surfaces():
    """Verify that an active verified mass-hiring opportunity outside the first 1000 rows
    enters candidate consideration and is prioritized."""
    now_iso = datetime.now(timezone.utc).isoformat()
    old_iso = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()

    jobs = [
        NormalizedJob(
            id=f"job-{i}",
            external_job_id=f"job-{i}",
            title=f"Software Engineer {i}",
            company=f"Enterprise {i % 15}",
            location="Bengaluru, India",
            skills=["python"],
            posted_date=now_iso,
        )
        for i in range(1000)
    ]

    outside_mass = NormalizedJob(
        id="mass-hiring-drive",
        external_job_id="mass-hiring-drive",
        title="Software Engineer - Mega Campus Hiring",
        company="TechGiants",
        location="Bengaluru, India",
        skills=["python"],
        mass_hiring="VERIFIED_MASS_HIRING",
        mass_hiring_status="ACTIVE",
        posted_date=old_iso,
    )
    jobs.append(outside_mass)

    repo = MockAuditedJobRepository(jobs)
    profile = UserProfile(
        id="candidate-1",
        desired_role="Software Engineer",
        skills=["python"],
        preferred_locations=["Bengaluru"],
    )
    mock_prof_repo = type("MockProf", (), {"get_profile": lambda s, uid: profile})()

    service = JobRelevanceService(
        job_repository=repo,
        profile_repository=mock_prof_repo,
        personalized_service=PersonalizedJobService(),
    )

    ranked_page1, total = service.get_relevant_jobs(user_id="candidate-1", page=1, page_size=20)

    assert total == 1001
    top_ids = [j.external_job_id for j in ranked_page1]
    assert outside_mass.external_job_id in top_ids, "Verified active mass-hiring must surface on page 1"


def test_pagination_accuracy_no_premature_empty_pages():
    """Verify that pagination metadata accurately matches the candidate universe,
    pages never become empty prematurely, and no duplicates exist across pages."""
    now_iso = datetime.now(timezone.utc).isoformat()
    jobs = [
        NormalizedJob(
            id=f"j-{i}",
            external_job_id=f"j-{i}",
            title=f"Developer {i}" if i < 1000 else f"Junior Developer {i}",
            company=f"Company {i % 30}",
            location="Bengaluru, India",
            skills=["python"],
            posted_date=now_iso,
        )
        for i in range(1050)
    ]

    repo = MockAuditedJobRepository(jobs)
    service = JobRelevanceService(
        job_repository=repo,
        personalized_service=PersonalizedJobService(),
    )

    page_size = 20
    p1, t1 = service.get_relevant_jobs(user_id=None, page=1, page_size=page_size)
    p2, t2 = service.get_relevant_jobs(user_id=None, page=2, page_size=page_size)
    p52, t52 = service.get_relevant_jobs(user_id=None, page=52, page_size=page_size)
    p53, t53 = service.get_relevant_jobs(user_id=None, page=53, page_size=page_size)
    p54, t54 = service.get_relevant_jobs(user_id=None, page=54, page_size=page_size)

    assert t1 == 1050
    assert len(p1) == 20
    assert len(p2) == 20
    assert len(p52) == 20
    assert len(p53) == 10
    assert len(p54) == 0

    p1_ids = {j.external_job_id for j in p1}
    p2_ids = {j.external_job_id for j in p2}
    p52_ids = {j.external_job_id for j in p52}
    p53_ids = {j.external_job_id for j in p53}

    assert len(p1_ids.intersection(p2_ids)) == 0
    assert len(p1_ids.intersection(p52_ids)) == 0
    assert len(p52_ids.intersection(p53_ids)) == 0

    repeat_p1, _ = service.get_relevant_jobs(user_id=None, page=1, page_size=page_size)
    assert [j.external_job_id for j in repeat_p1] == [j.external_job_id for j in p1]
