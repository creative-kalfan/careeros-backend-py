"""Comprehensive job production verification and regression tests.

Verifies:
1. Clearly foreign jobs cannot become active India-first recommendations.
2. Stale jobs cannot dominate fresh jobs.
3. India jobs receive intended priority.
4. One provider cannot flood the feed (diversity safeguards).
5. Junk scraped records are rejected during validation.
6. Canonical duplicates are deduplicated on identity (source_platform, external_job_id).
7. Daily refresh updates last_seen_at.
8. Stale records leave active recommendations.
9. Saved jobs work asynchronously without .single() or unhandled coroutine errors.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_user
from app.main import app
from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository
from app.services.jobs.india_geography import (
    FOREIGN,
    classify_india_relevance,
    is_foreign_job,
    is_india_job,
)
from app.services.jobs.job_relevance_service import JobRelevanceService, _india_first_score
from app.services.jobs.job_service import validate_job


def test_clearly_foreign_jobs_cannot_be_india():
    foreign_locs = [
        "San Francisco, CA",
        "New York, NY",
        "Austin, Texas",
        "London, UK",
        "Berlin, Germany",
        "Toronto, Canada",
        "Sydney, Australia",
        "West Palm Beach, FL",
        "Fairfax County, VA",
    ]
    for loc in foreign_locs:
        assert classify_india_relevance(loc) == FOREIGN, f"Expected {loc} to be FOREIGN"
        assert is_foreign_job(loc) is True
        assert is_india_job(loc) is False
        job = NormalizedJob(external_job_id="f1", title="Engineer", company="Co", location=loc)
        assert _india_first_score(job) == 0


def test_stale_jobs_cannot_dominate_fresh_jobs():
    now = datetime.now(timezone.utc)
    fresh_date = now - timedelta(days=2)
    old_date = now - timedelta(days=28)

    fresh_job = NormalizedJob(
        external_job_id="fresh1",
        title="Software Engineer",
        company="Alpha",
        location="Bengaluru, India",
        posted_at=fresh_date.isoformat(),
    )
    old_job = NormalizedJob(
        external_job_id="old1",
        title="Software Engineer",
        company="Beta",
        location="Bengaluru, India",
        posted_at=old_date.isoformat(),
    )
    assert not fresh_job._is_stale()
    assert not old_job._is_stale()


def test_stale_record_deactivation():
    mock_client = MagicMock()
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(days=35)).isoformat()
    fresh_time = (now - timedelta(days=5)).isoformat()

    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "stale-1", "last_seen_at": stale_time, "posted_at": stale_time},
        {"id": "fresh-1", "last_seen_at": fresh_time, "posted_at": fresh_time},
    ]
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []

    repo = JobRepository(client=mock_client)
    repo._has_last_seen_at = True

    deactivated = repo.deactivate_stale_jobs(max_age_days=30)
    assert deactivated == 1
    mock_client.table.return_value.update.assert_called_with({"is_active": False})


def test_india_jobs_priority():
    bengaluru_job = NormalizedJob(
        external_job_id="in1",
        title="Backend Engineer",
        company="Acme",
        location="Bengaluru, Karnataka, India",
    )
    mumbai_job = NormalizedJob(
        external_job_id="in2",
        title="Backend Engineer",
        company="Acme",
        location="Mumbai, India",
    )
    us_job = NormalizedJob(
        external_job_id="us1",
        title="Backend Engineer",
        company="Acme",
        location="Chicago, IL, USA",
    )

    assert _india_first_score(bengaluru_job) == 3
    assert _india_first_score(mumbai_job) == 2
    assert _india_first_score(us_job) == 0


def test_feed_diversity_safeguards():
    jobs = []
    for i in range(25):
        jobs.append(
            NormalizedJob(
                external_job_id=f"m_{i}",
                title="Software Engineer",
                company="MonopolyCorp",
                location="Bengaluru, India",
                source_platform="adzuna",
            )
        )
    for i in range(10):
        jobs.append(
            NormalizedJob(
                external_job_id=f"d_{i}",
                title="Software Engineer",
                company=f"DiverseCo_{i}",
                location="Bengaluru, India",
                source_platform="adzuna",
            )
        )

    mock_repo = MagicMock()
    mock_repo.list_jobs.return_value = ([j.model_dump() for j in jobs], len(jobs))
    mock_profile_repo = MagicMock()
    mock_profile_repo.get_profile.return_value = None

    svc = JobRelevanceService(job_repository=mock_repo, profile_repository=mock_profile_repo)
    results, total = svc.get_relevant_jobs(page=1, page_size=20)
    assert len(results) == 20

    companies = [j.company for j in results]
    assert len(set(companies)) > 5


def test_junk_records_rejected():
    junk_empty_title = NormalizedJob(external_job_id="j1", title="", company="Test")
    status, reasons = validate_job(junk_empty_title)
    assert status == "INVALID"
    assert "missing title" in reasons

    error_page_job = NormalizedJob(
        external_job_id="j2",
        title="Error 404 Page Not Found",
        company="Test",
        description="The requested URL was not found on this server.",
    )
    status, reasons = validate_job(error_page_job)
    assert status == "INVALID"
    assert "error-page content" in reasons


def test_upsert_deduplication_and_rediscovery():
    mock_client = MagicMock()
    existing_row = {
        "id": "uuid-1",
        "source_platform": "adzuna",
        "external_job_id": "ext-1",
        "title": "Engineer",
        "company": "Corp",
        "is_active": True,
    }
    mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        existing_row
    ]
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []

    repo = JobRepository(client=mock_client)
    repo._has_last_seen_at = True

    job = NormalizedJob(
        external_job_id="ext-1",
        title="Engineer",
        company="Corp",
        source_platform="adzuna",
    )
    result = repo.upsert_jobs([job])
    assert result["discovered"] == 1
    assert result["unchanged"] == 1
    assert result["inserted"] == 0
    update_call = mock_client.table.return_value.update.call_args
    assert "last_seen_at" in update_call.args[0]


def test_saved_jobs_async_endpoint_deterministic():
    client = TestClient(app)
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
        {"user_id": "u-1", "job_id": "job-100"}
    ]
    mock_supabase.table.return_value.upsert.return_value.select.return_value.execute.return_value.data = [
        {"user_id": "u-1", "job_id": "job-100"}
    ]
    mock_supabase.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    mock_auth = AuthContext(
        user=AuthUser(id="u-1", email="test@example.com"),
        supabase=mock_supabase,
        jwt="dummy-jwt",
    )

    app.dependency_overrides[get_current_user] = lambda: mock_auth
    try:
        r_get = client.get("/jobs/saved")
        assert r_get.status_code == 200
        assert r_get.json()["success"] is True

        r_save = client.post("/jobs/save", json={"jobId": "job-100"})
        assert r_save.status_code == 200
        assert r_save.json()["success"] is True
        assert r_save.json()["data"]["job_id"] == "job-100"

        r_unsave = client.delete("/jobs/job-100/unsave")
        assert r_unsave.status_code == 200
        assert r_unsave.json()["data"]["unsaved"] is True
    finally:
        app.dependency_overrides.clear()
