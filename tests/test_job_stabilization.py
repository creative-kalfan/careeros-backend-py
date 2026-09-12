"""Stabilization regression: salary contract, fresher, search aliases, includeAts."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_job_relevance_service
from app.main import app
from app.models.job import NormalizedJob
from app.schemas.job import JobOut
from app.services.jobs.job_relevance_service import JobRelevanceService


def _svc_with_jobs(jobs):
    repo = MagicMock()
    rows = [j if isinstance(j, dict) else j.model_dump() for j in jobs]
    repo.list_jobs.return_value = (rows, len(rows))
    profile_repo = MagicMock()
    profile_repo.get_profile.return_value = None
    return JobRelevanceService(job_repository=repo, profile_repository=profile_repo)


def test_jobout_preserves_numeric_salary():
    row = {
        "id": "1",
        "title": "Dev",
        "company": "Acme",
        "salary": None,
        "salary_min": 80000,
        "salary_max": 120000,
        "salary_currency": "USD",
    }
    out = JobOut.from_db_row(row)
    assert out.salary_min == 80000
    assert out.salary_max == 120000
    assert out.salary_currency == "USD"
    assert out.salary is None  # unknown stays unknown, never fabricated


def test_jobout_preserves_salary_string_when_present():
    out = JobOut.from_db_row({"id": "1", "title": "Dev", "company": "A", "salary": "$80k - $120k"})
    assert out.salary == "$80k - $120k"


def test_fresher_behaves_as_entry():
    svc = _svc_with_jobs(
        [
            NormalizedJob(external_job_id="e1", title="Junior Dev", company="A", experience_level="Junior"),
            NormalizedJob(external_job_id="e2", title="Senior Dev", company="B", experience_level="Senior"),
            NormalizedJob(external_job_id="e3", title="ML Intern", company="C", experience_level="Intern"),
        ]
    )
    jobs, total = svc.get_relevant_jobs(experience="Fresher")
    assert total == 2
    assert {j.external_job_id for j in jobs} == {"e1", "e3"}


def test_search_accepts_snake_case_aliases():
    client = TestClient(app)
    service = MagicMock()
    service.get_relevant_jobs.return_value = ([], 0)
    app.dependency_overrides[get_job_relevance_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: MagicMock(user=MagicMock(id="u"))
    try:
        r = client.post(
            "/jobs/search",
            json={"page_size": 7, "employment_type": "Contract", "employmentType": None},
        )
        assert r.status_code == 200
        kwargs = service.get_relevant_jobs.call_args.kwargs
        assert kwargs["page_size"] == 7
        assert kwargs["employment_type"] == "Contract"
    finally:
        app.dependency_overrides.clear()


def test_personalized_accepts_includeAts_camelcase():
    client = TestClient(app)
    service = MagicMock()
    service.get_relevant_jobs.return_value = ([], 0)
    app.dependency_overrides[get_job_relevance_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: MagicMock(user=MagicMock(id="u"))
    try:
        r = client.get("/jobs/personalized?includeAts=true")
        assert r.status_code == 200
        r = client.get("/jobs/personalized?include_ats=true")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()
