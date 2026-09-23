"""Tests for seniority classification, mass hiring detection, and opportunity ranking."""

from datetime import datetime, timezone, timedelta
import pytest
from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.services.jobs.extraction_utils import classify_seniority
from app.services.jobs.mass_hiring_detector import detect_mass_hiring
from app.services.jobs.job_relevance_service import (
    JobRelevanceService,
    _get_job_seniority,
    _is_entry_or_fresher,
    _is_verified_active_mass_hiring,
)
from app.services.jobs.personalized_job_service import PersonalizedJobService


def test_seniority_classification_fresher():
    assert classify_seniority("Looking for freshers to join", "Software Engineer")[0] == "entry"
    assert classify_seniority("Trainee engineer role", "Graduate Trainee")[0] == "entry"
    assert classify_seniority("Require 0-1 years of experience", "Data Analyst")[0] == "entry"
    assert classify_seniority("0 to 2 years experience", "Python Developer")[0] == "entry"
    assert classify_seniority("0 years experience required", "Junior Analyst")[0] == "entry"


def test_seniority_classification_mid_experience_range():
    # 2-5 years experience is mid-level, not entry/fresher
    assert classify_seniority("Sales incentives and commissions with 2-5 years experience", "Data Analyst")[0] == "mid"
    assert classify_seniority("Requires 2 to 5 yrs experience", "Data Analyst")[0] == "mid"
    job = NormalizedJob(
        title="Data Analyst",
        company="SalesCo",
        description="Responsible for sales operations and commissions. 2-5 years experience required.",
    )
    assert _get_job_seniority(job) == "mid"
    assert _is_entry_or_fresher(job) is False


def test_seniority_classification_associate():
    # Context indicates junior/entry
    assert classify_seniority("Entry level associate role, 0-1 yrs", "Associate Developer")[0] == "entry"
    # Context does not indicate entry -> mid
    assert classify_seniority("Responsible for enterprise systems", "Associate")[0] == "mid"


def test_seniority_classification_senior_staff():
    assert classify_seniority("10+ years experience", "Senior Backend Engineer")[0] == "senior"
    assert classify_seniority("Principal architect", "Staff Software Engineer")[0] == "principal"
    # Leadership titles take precedence over educational qualifications in body
    assert classify_seniority("Candidate must be graduate or above", "Team Leader - Operations")[0] == "lead"
    assert classify_seniority("Candidate must be graduate", "Engineering Manager")[0] == "manager"


def test_mass_hiring_detection_verified():
    res = detect_mass_hiring(
        title="Fresher Hiring Drive 2026",
        description="Mega walk-in drive for freshers with 100+ openings across Bangalore. Apply by 2026-12-31.",
    )
    assert res["confidence"] == "VERIFIED_MASS_HIRING"
    assert res["status"] == "ACTIVE"
    assert res["vacancy_count"] == 100
    assert len(res["signals_detected"]) >= 2


def test_mass_hiring_detection_not_mass():
    res = detect_mass_hiring(
        title="Senior React Developer",
        description="We are looking for an experienced developer to join our team of 5 engineers.",
    )
    assert res["confidence"] == "NOT_MASS_HIRING"
    assert res["status"] == "UNKNOWN"
    assert res["vacancy_count"] is None


def test_mass_hiring_detection_false_positives():
    """Incidental mentions must NOT be classified as verified mass hiring."""
    # Vendor sales phrasing
    res1 = detect_mass_hiring(
        title="Account Executive",
        description="We provide mass hiring solutions for high-growth enterprises.",
    )
    assert res1["confidence"] == "NOT_MASS_HIRING"

    # Recruiter prior experience requirement
    res2 = detect_mass_hiring(
        title="Talent Acquisition Specialist",
        description="Candidate must have previous hiring drive experience.",
    )
    assert res2["confidence"] == "NOT_MASS_HIRING"

    # Incidental campus hiring mention
    res3 = detect_mass_hiring(
        title="HR Coordinator",
        description="3+ years experience in campus hiring operations.",
    )
    assert res3["confidence"] == "NOT_MASS_HIRING"


def test_mass_hiring_detection_expired():
    res = detect_mass_hiring(
        title="Mega Recruitment Drive",
        description="Walk-in drive for freshers. Deadline: 2020-01-01.",
    )
    assert res["confidence"] == "VERIFIED_MASS_HIRING"
    assert res["status"] == "EXPIRED"


def test_mass_hiring_lifecycle_dates():
    """Verify ACTIVE, ENDING_SOON, EXPIRED, and UNKNOWN date handling."""
    now = datetime.now(timezone.utc)
    future_date = (now + timedelta(days=20)).strftime("%Y-%m-%d")
    soon_date = (now + timedelta(days=3)).strftime("%Y-%m-%d")
    past_date = (now - timedelta(days=5)).strftime("%Y-%m-%d")

    # Future deadline > 7 days -> ACTIVE
    res_active = detect_mass_hiring(
        title="Mega Hiring Drive",
        description=f"Walk-in drive for developers. Deadline: {future_date}",
    )
    assert res_active["status"] == "ACTIVE"

    # Deadline <= 7 days -> ENDING_SOON
    res_soon = detect_mass_hiring(
        title="Mega Hiring Drive",
        description=f"Walk-in drive for developers. Deadline: {soon_date}",
    )
    assert res_soon["status"] == "ENDING_SOON"

    # Past deadline -> EXPIRED
    res_expired = detect_mass_hiring(
        title="Mega Hiring Drive",
        description=f"Walk-in drive for developers. Deadline: {past_date}",
    )
    assert res_expired["status"] == "EXPIRED"

    # Unparseable deadline does not fabricate a date -> UNKNOWN
    res_unknown = detect_mass_hiring(
        title="Mega Hiring Drive",
        description="Walk-in drive for developers. Deadline: TBD soon",
    )
    assert res_unknown["status"] == "UNKNOWN"


def test_freshness_mass_hiring_override():
    service = PersonalizedJobService()
    # Normal 45-day old job
    old_job = NormalizedJob(
        title="Backend Engineer",
        company="Corp A",
        posted_date="2026-01-01T00:00:00Z",
    )
    score_normal = service._score_freshness(old_job)
    assert score_normal <= 20.0

    # 45-day old active mass hiring job receives bounded baseline (85.0)
    mass_job = NormalizedJob(
        title="Bulk Hiring - Backend Engineer",
        company="Corp B",
        posted_date="2026-01-01T00:00:00Z",
        mass_hiring="VERIFIED_MASS_HIRING",
        mass_hiring_status="ACTIVE",
    )
    score_mass = service._score_freshness(mass_job)
    assert score_mass == 85.0

    # Expired mass hiring job loses override
    expired_job = NormalizedJob(
        title="Bulk Hiring - Backend Engineer",
        company="Corp C",
        posted_date="2026-01-01T00:00:00Z",
        mass_hiring="VERIFIED_MASS_HIRING",
        mass_hiring_status="EXPIRED",
    )
    score_expired = service._score_freshness(expired_job)
    assert score_expired <= 20.0


def test_unauth_opportunity_ranking_fresher_first():
    entry_job = NormalizedJob(
        title="Junior Data Analyst",
        company="EntryCorp",
        location="Bengaluru, India",
        experience_level="Entry",
        posted_date="2026-09-16T00:00:00Z",
    )
    senior_job = NormalizedJob(
        title="Senior Data Quality Engineer",
        company="SeniorCorp",
        location="Bengaluru, India",
        experience_level="Senior",
        posted_date="2026-08-01T00:00:00Z",
    )
    assert _is_entry_or_fresher(entry_job) is True
    assert _is_entry_or_fresher(senior_job) is False


class MockJobRepository:
    def __init__(self, jobs):
        self.jobs = jobs

    def list_jobs(self, page=1, page_size=20, **kwargs):
        return [j.model_dump() for j in self.jobs], len(self.jobs)


class MockProfileRepository:
    def __init__(self, profile):
        self.profile = profile

    def get_profile(self, user_id):
        return self.profile


def test_ranking_sanity_cases():
    """Prove Section 3 and Section 9 ranking behavior cases."""
    now_iso = datetime.now(timezone.utc).isoformat()
    old_iso = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()

    # 1. Fresh highly relevant entry job vs old weakly relevant job
    fresh_entry = NormalizedJob(
        id="1",
        title="Junior Backend Developer",
        company="TechCorp",
        location="Bengaluru, India",
        posted_date=now_iso,
        skills=["Python", "FastAPI"],
    )
    old_weak = NormalizedJob(
        id="2",
        title="Senior Java Architect",
        company="LegacyCorp",
        location="Frankfurt, Germany",
        posted_date=old_iso,
        skills=["Cobol"],
    )

    profile = UserProfile(
        id="user1",
        desired_role="Backend Engineer",
        skills=["Python", "FastAPI"],
        preferred_locations=["Bengaluru"],
    )

    service = JobRelevanceService(
        job_repository=MockJobRepository([old_weak, fresh_entry]),
        profile_repository=MockProfileRepository(profile),
    )
    ranked, _ = service.get_relevant_jobs(user_id="user1", page=1, page_size=10)
    assert ranked[0].id == fresh_entry.id, "Fresh highly relevant entry job must outrank old weak job"

    # 2. Relevant active mass-hiring job vs older normal job
    active_mass = NormalizedJob(
        id="3",
        title="Bulk Hiring - Backend Engineer",
        company="MassCorp",
        location="Bengaluru, India",
        posted_date=old_iso,
        skills=["Python", "SQL"],
        mass_hiring="VERIFIED_MASS_HIRING",
        mass_hiring_status="ACTIVE",
    )
    old_normal = NormalizedJob(
        id="4",
        title="Backend Engineer",
        company="NormCorp",
        location="Bengaluru, India",
        posted_date=old_iso,
        skills=["Python", "SQL"],
    )

    service_mass = JobRelevanceService(
        job_repository=MockJobRepository([old_normal, active_mass]),
        profile_repository=MockProfileRepository(profile),
    )
    ranked_mass, _ = service_mass.get_relevant_jobs(user_id="user1", page=1, page_size=10)
    assert ranked_mass[0].id == active_mass.id, "Relevant active mass-hiring job must outrank older normal job"

    # 3. Active mass-hiring does NOT bypass semantic relevance
    unrelated_mass = NormalizedJob(
        id="5",
        title="Customer Support Executive - Bulk Hiring",
        company="SupportCorp",
        location="Bengaluru, India",
        posted_date=now_iso,
        skills=["Customer Service", "Telecalling"],
        mass_hiring="VERIFIED_MASS_HIRING",
        mass_hiring_status="ACTIVE",
    )
    relevant_normal_fresh = NormalizedJob(
        id="6",
        title="Python Backend Engineer",
        company="PyCorp",
        location="Bengaluru, India",
        posted_date=now_iso,
        skills=["Python", "FastAPI"],
    )

    service_rel = JobRelevanceService(
        job_repository=MockJobRepository([unrelated_mass, relevant_normal_fresh]),
        profile_repository=MockProfileRepository(profile),
    )
    ranked_rel, _ = service_rel.get_relevant_jobs(user_id="user1", page=1, page_size=10)
    assert ranked_rel[0].id == relevant_normal_fresh.id, "Relevant normal fresh job must outrank unrelated mass hiring job"

    # 4. Expired mass-hiring loses special priority
    expired_mass = NormalizedJob(
        id="7",
        title="Bulk Hiring - Backend Engineer",
        company="ExpiredCorp",
        location="Bengaluru, India",
        posted_date=now_iso,
        skills=["Python", "FastAPI"],
        mass_hiring="VERIFIED_MASS_HIRING",
        mass_hiring_status="EXPIRED",
    )

    service_exp = JobRelevanceService(
        job_repository=MockJobRepository([expired_mass, relevant_normal_fresh]),
        profile_repository=MockProfileRepository(profile),
    )
    ranked_exp, _ = service_exp.get_relevant_jobs(user_id="user1", page=1, page_size=10)
    assert ranked_exp[0].id == relevant_normal_fresh.id, "Fresh normal job must outrank expired mass hiring"

    # 5. Explicit Newest sort remains genuinely newest
    newer_job = NormalizedJob(
        id="8",
        title="Junior Backend Developer",
        company="NewCorp",
        posted_date="2026-09-17T08:00:00Z",
    )
    older_job = NormalizedJob(
        id="9",
        title="Bulk Hiring - Backend Developer",
        company="OldCorp",
        posted_date="2026-09-10T08:00:00Z",
        mass_hiring="VERIFIED_MASS_HIRING",
        mass_hiring_status="ACTIVE",
    )
    service_sort = JobRelevanceService(
        job_repository=MockJobRepository([older_job, newer_job]),
        profile_repository=MockProfileRepository(None),
    )
    ranked_newest, _ = service_sort.get_relevant_jobs(page=1, page_size=10, sort="newest")
    assert ranked_newest[0].id == newer_job.id, "Explicit newest sort must order by posting date strictly"
