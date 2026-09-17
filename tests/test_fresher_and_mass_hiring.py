"""Tests for seniority classification, mass hiring detection, and opportunity ranking."""

import pytest
from app.models.job import NormalizedJob
from app.services.jobs.extraction_utils import classify_seniority
from app.services.jobs.mass_hiring_detector import detect_mass_hiring
from app.services.jobs.job_relevance_service import (
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


def test_seniority_classification_associate():
    # Context indicates junior/entry
    assert classify_seniority("Entry level associate role, 0-1 yrs", "Associate Developer")[0] == "entry"
    # Context does not indicate entry -> mid
    assert classify_seniority("Responsible for enterprise systems", "Associate")[0] == "mid"


def test_seniority_classification_senior_staff():
    assert classify_seniority("10+ years experience", "Senior Backend Engineer")[0] == "senior"
    assert classify_seniority("Principal architect", "Staff Software Engineer")[0] == "principal"


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


def test_mass_hiring_detection_expired():
    res = detect_mass_hiring(
        title="Mega Recruitment Drive",
        description="Walk-in drive for freshers. Deadline: 2020-01-01.",
    )
    assert res["confidence"] == "VERIFIED_MASS_HIRING"
    assert res["status"] == "EXPIRED"


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

    # 45-day old active mass hiring job
    mass_job = NormalizedJob(
        title="Bulk Hiring - Backend Engineer",
        company="Corp B",
        posted_date="2026-01-01T00:00:00Z",
        mass_hiring="VERIFIED_MASS_HIRING",
        mass_hiring_status="ACTIVE",
    )
    score_mass = service._score_freshness(mass_job)
    assert score_mass >= 90.0

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
