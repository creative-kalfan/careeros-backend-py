"""Regression tests for the Job Intelligence filter audit.

Covers the confirmed production defects with prod-like jobs
(``experience_level`` NULL, remote flag/location disagreeing):
Entry inference (fresher wording, years ranges, "Entry Level" stored value),
the single remote definition, and camelCase ``pageSize`` on the GET routes.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_job_relevance_service
from app.main import app
from app.models.job import NormalizedJob
from app.services.jobs.job_relevance_service import JobRelevanceService


def _prod_like_jobs() -> list[NormalizedJob]:
    return [
        # Fresher wording, no explicit level (India-market entry signal).
        NormalizedJob(
            external_job_id="e-fresher", title="Software Engineer", company="Acme",
            location="Bengaluru, India",
            description="Calling all freshers! 0-1 years experience welcome.",
        ),
        # Years range only, no seniority keyword.
        NormalizedJob(
            external_job_id="e-years", title="Backend Developer", company="Acme",
            location="Pune, India",
            description="Requires 1-2 years of Python experience.",
        ),
        # Free-form stored level.
        NormalizedJob(
            external_job_id="e-stored", title="Developer", company="Acme",
            location="Remote", experience_level="Entry Level",
            description="Great role.",
        ),
        # Flag-remote with a plain city location (Ashby-style).
        NormalizedJob(
            external_job_id="r-flag", title="Dev", company="X",
            location="Bengaluru, India", remote=True, description="x",
        ),
        # Remote location with an unset flag (Firecrawl-style gap).
        NormalizedJob(
            external_job_id="r-loc", title="Dev", company="Y",
            location="Remote - India", remote=None, description="y",
        ),
    ]


@pytest.fixture
def svc():
    repo = MagicMock()
    jobs = _prod_like_jobs()
    repo.list_jobs.return_value = ([j.model_dump() for j in jobs], len(jobs))
    profile_repo = MagicMock()
    profile_repo.get_profile.return_value = None
    return JobRelevanceService(
        job_repository=repo, profile_repository=profile_repo
    )


def test_entry_finds_fresher_years_and_stored_levels(svc):
    jobs, total = svc.get_relevant_jobs(experience="Entry")
    assert total == 3
    assert {j.external_job_id for j in jobs} == {
        "e-fresher", "e-years", "e-stored",
    }


def test_remote_true_uses_flag_or_location(svc):
    jobs, total = svc.get_relevant_jobs(remote=True)
    # r-flag (flag set), r-loc (Remote location, flag unset),
    # e-stored (Remote location, flag unset).
    assert total == 3
    assert {j.external_job_id for j in jobs} == {"r-flag", "r-loc", "e-stored"}


def test_remote_false_excludes_remote_locations(svc):
    jobs, total = svc.get_relevant_jobs(remote=False)
    assert "r-loc" not in {j.external_job_id for j in jobs}
    assert "r-flag" not in {j.external_job_id for j in jobs}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_service():
    service = MagicMock()
    service.get_relevant_jobs.return_value = ([], 0)
    return service


@pytest.fixture
def override_deps(client, mock_service):
    app.dependency_overrides[get_job_relevance_service] = lambda: mock_service
    app.dependency_overrides[get_current_user] = lambda: MagicMock(
        user=MagicMock(id="user-123")
    )
    yield mock_service
    app.dependency_overrides.clear()


def test_list_jobs_accepts_camelcase_pagesize(client, override_deps):
    response = client.get("/jobs?page=1&pageSize=7")
    assert response.status_code == 200
    assert override_deps.get_relevant_jobs.call_args.kwargs["page_size"] == 7


def test_list_jobs_still_accepts_snake_pagesize(client, override_deps):
    response = client.get("/jobs?page=1&page_size=5")
    assert response.status_code == 200
    assert override_deps.get_relevant_jobs.call_args.kwargs["page_size"] == 5
