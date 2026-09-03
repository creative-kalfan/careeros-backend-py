"""Comprehensive unit and integration tests for multi-parameter job filtering, sorting, and pagination."""

from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.repositories.job_repository import JobRepository
from app.services.jobs.job_relevance_service import JobRelevanceService
from app.dependencies import get_current_user, get_job_relevance_service


# ---------------------------------------------------------------------------
# Test Fixtures & Sample Dataset
# ---------------------------------------------------------------------------

def create_sample_jobs() -> list[NormalizedJob]:
    """Create a rich dataset of NormalizedJob objects for filtering tests."""
    return [
        NormalizedJob(
            external_job_id="job-1",
            title="Senior Python Backend Engineer",
            company="Acme Corp",
            location="Bengaluru, India",
            remote=False,
            workplace_type="On-site",
            employment_type="Full-time",
            experience_level="Senior",
            salary="$140,000 - $180,000",
            salary_min=140000.0,
            salary_max=180000.0,
            skills=["Python", "FastAPI", "PostgreSQL", "Docker"],
            posted_date="2026-08-25T10:00:00Z",
            description="We are seeking a senior Python developer with FastAPI and PostgreSQL expertise.",
        ),
        NormalizedJob(
            external_job_id="job-2",
            title="Junior Frontend Developer",
            company="Acme Corp",
            location="Remote",
            remote=True,
            workplace_type="Remote",
            employment_type="Full-time",
            experience_level="Junior",
            salary="$70,000 - $90,000",
            salary_min=70000.0,
            salary_max=90000.0,
            skills=["TypeScript", "React", "TailwindCSS"],
            posted_date="2026-08-26T12:00:00Z",
            description="Entry level role for React frontend development.",
        ),
        NormalizedJob(
            external_job_id="job-3",
            title="Lead DevOps Architect",
            company="Beta Labs",
            location="San Francisco, CA",
            remote=False,
            workplace_type="On-site",
            employment_type="Contract",
            experience_level="Staff",
            salary="$200,000 - $250,000",
            salary_min=200000.0,
            salary_max=250000.0,
            skills=["Kubernetes", "AWS", "Terraform", "Python"],
            posted_date="2026-08-20T08:00:00Z",
            description="Contract position leading cloud infrastructure on AWS and Kubernetes.",
        ),
        NormalizedJob(
            external_job_id="job-4",
            title="Machine Learning Intern",
            company="Beta Labs",
            location="Hyderabad, India (Remote)",
            remote=True,
            workplace_type="Remote",
            employment_type="Internship",
            experience_level="Intern",
            salary="$30,000 - $40,000",
            salary_min=30000.0,
            salary_max=40000.0,
            skills=["Python", "PyTorch", "NLP"],
            posted_date="2026-08-27T09:00:00Z",
            description="Summer internship in NLP and machine learning.",
        ),
        NormalizedJob(
            external_job_id="job-5",
            title="Mid-Level Fullstack Engineer",
            company="Gamma Innovations",
            location="London, UK",
            remote=False,
            workplace_type="Hybrid",
            employment_type="Part-time",
            experience_level="Mid",
            salary="$80,000 - $110,000",
            salary_min=80000.0,
            salary_max=110000.0,
            skills=["JavaScript", "Node.js", "React", "PostgreSQL"],
            posted_date="2026-08-22T15:00:00Z",
            description="Part-time full stack engineer working on React and Node services.",
        ),
        NormalizedJob(
            external_job_id="job-6",
            title="Principal Staff Engineer",
            company="Delta Technologies",
            location="Remote - India",
            remote=True,
            workplace_type="Remote",
            employment_type="Full-time",
            experience_level="Principal",
            salary="$220,000 - $280,000",
            salary_min=220000.0,
            salary_max=280000.0,
            skills=["Go", "Rust", "Distributed Systems", "Kubernetes"],
            posted_date="2026-08-24T11:00:00Z",
            description="Principal distributed systems engineer.",
        ),
    ]


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    sample_jobs = create_sample_jobs()
    repo.list_jobs.return_value = (sample_jobs, len(sample_jobs))
    return repo


@pytest.fixture
def mock_profile_repo():
    repo = MagicMock()
    repo.get_profile.return_value = None
    return repo


@pytest.fixture
def relevance_svc(mock_repo, mock_profile_repo):
    return JobRelevanceService(
        job_repository=mock_repo,
        profile_repository=mock_profile_repo,
    )


# ---------------------------------------------------------------------------
# Unit Tests: JobRelevanceService Filtering
# ---------------------------------------------------------------------------

class TestJobRelevanceServiceFiltering:
    """Test suite for individual and combined filtering in JobRelevanceService."""

    def test_filter_by_company(self, relevance_svc):
        """Test substring and case-insensitive matching on company name."""
        jobs, total = relevance_svc.get_relevant_jobs(company="acme")
        assert total == 2
        assert all(j.company == "Acme Corp" for j in jobs)

        jobs, total = relevance_svc.get_relevant_jobs(company="Beta")
        assert total == 2
        assert all(j.company == "Beta Labs" for j in jobs)

        jobs, total = relevance_svc.get_relevant_jobs(company="NonExistent")
        assert total == 0
        assert len(jobs) == 0

    def test_filter_by_remote_true(self, relevance_svc):
        """Test remote=True filters for remote jobs correctly."""
        jobs, total = relevance_svc.get_relevant_jobs(remote=True)
        assert total == 3
        ids = {j.external_job_id for j in jobs}
        assert ids == {"job-2", "job-4", "job-6"}

    def test_filter_by_remote_false(self, relevance_svc):
        """Test remote=False filters for non-remote jobs correctly."""
        jobs, total = relevance_svc.get_relevant_jobs(remote=False)
        assert total == 3
        ids = {j.external_job_id for j in jobs}
        assert ids == {"job-1", "job-3", "job-5"}

    def test_filter_by_skills_list(self, relevance_svc):
        """Test filtering by a list of skills."""
        jobs, total = relevance_svc.get_relevant_jobs(skills=["FastAPI"])
        assert total == 1
        assert jobs[0].external_job_id == "job-1"

        jobs, total = relevance_svc.get_relevant_jobs(skills=["React"])
        assert total == 2
        ids = {j.external_job_id for j in jobs}
        assert ids == {"job-2", "job-5"}

    def test_filter_by_skills_comma_string(self, relevance_svc):
        """Test filtering by comma-separated skills string."""
        jobs, total = relevance_svc.get_relevant_jobs(skills="PyTorch, Kubernetes")
        assert total == 3
        ids = {j.external_job_id for j in jobs}
        assert ids == {"job-3", "job-4", "job-6"}

    def test_filter_by_employment_type(self, relevance_svc):
        """Test filtering by exact and fuzzy employment types."""
        # Full-time
        jobs, total = relevance_svc.get_relevant_jobs(employment_type="Full-time")
        assert total == 3
        ids = {j.external_job_id for j in jobs}
        assert ids == {"job-1", "job-2", "job-6"}

        # Contract
        jobs, total = relevance_svc.get_relevant_jobs(employment_type="Contract")
        assert total == 1
        assert jobs[0].external_job_id == "job-3"

        # Internship
        jobs, total = relevance_svc.get_relevant_jobs(employment_type="Internship")
        assert total == 1
        assert jobs[0].external_job_id == "job-4"

        # Part-time
        jobs, total = relevance_svc.get_relevant_jobs(employment_type="Part-time")
        assert total == 1
        assert jobs[0].external_job_id == "job-5"

    def test_filter_by_experience(self, relevance_svc):
        """Test filtering by experience level."""
        # Senior
        jobs, total = relevance_svc.get_relevant_jobs(experience="Senior")
        assert total == 1
        assert jobs[0].external_job_id == "job-1"

        # Entry / Junior
        jobs, total = relevance_svc.get_relevant_jobs(experience="Junior")
        assert total == 2  # junior (job-2) + intern (job-4)
        ids = {j.external_job_id for j in jobs}
        assert ids == {"job-2", "job-4"}

        # Staff / Principal
        jobs, total = relevance_svc.get_relevant_jobs(experience="Staff")
        assert total == 2
        ids = {j.external_job_id for j in jobs}
        assert ids == {"job-3", "job-6"}

    def test_filter_combination(self, relevance_svc):
        """Test combining multiple filter parameters."""
        jobs, total = relevance_svc.get_relevant_jobs(
            company="Acme",
            remote=True,
            employment_type="Full-time",
            skills=["React"],
        )
        assert total == 1
        assert jobs[0].external_job_id == "job-2"


# ---------------------------------------------------------------------------
# Unit Tests: Sorting & Pagination
# ---------------------------------------------------------------------------

class TestJobRelevanceServiceSortingAndPagination:
    """Test suite for dynamic sorting and pagination accuracy."""

    def test_sort_newest(self, relevance_svc):
        """Test sorting by posted_date descending (newest first)."""
        jobs, total = relevance_svc.get_relevant_jobs(sort="newest")
        assert total == 6
        # job-4 is 2026-08-27, job-2 is 2026-08-26, job-1 is 2026-08-25
        assert jobs[0].external_job_id == "job-4"
        assert jobs[1].external_job_id == "job-2"
        assert jobs[2].external_job_id == "job-1"

    def test_sort_oldest(self, relevance_svc):
        """Test sorting by posted_date ascending (oldest first)."""
        jobs, total = relevance_svc.get_relevant_jobs(sort="oldest")
        assert total == 6
        # job-3 is 2026-08-20 (oldest)
        assert jobs[0].external_job_id == "job-3"

    def test_sort_salary(self, relevance_svc):
        """Test sorting by salary descending."""
        jobs, total = relevance_svc.get_relevant_jobs(sort="salary")
        assert total == 6
        # job-6 max is 280k, job-3 max is 250k, job-1 max is 180k
        assert jobs[0].external_job_id == "job-6"
        assert jobs[1].external_job_id == "job-3"
        assert jobs[2].external_job_id == "job-1"

    def test_pagination_accuracy(self, relevance_svc):
        """Test that pagination returns correct slices and total is preserved."""
        # Page 1, pageSize 2
        p1, total = relevance_svc.get_relevant_jobs(sort="newest", page=1, page_size=2)
        assert total == 6
        assert len(p1) == 2
        assert p1[0].external_job_id == "job-4"
        assert p1[1].external_job_id == "job-2"

        # Page 2, pageSize 2
        p2, total = relevance_svc.get_relevant_jobs(sort="newest", page=2, page_size=2)
        assert total == 6
        assert len(p2) == 2
        assert p2[0].external_job_id == "job-1"
        assert p2[1].external_job_id == "job-6"

        # Page 4, pageSize 2 (empty page beyond available items)
        p4, total = relevance_svc.get_relevant_jobs(sort="newest", page=4, page_size=2)
        assert total == 6
        assert len(p4) == 0

    def test_pagination_with_filtering(self, relevance_svc):
        """Test pagination accuracy when filters reduce the result set."""
        # Filter for remote=True (total 3 items), page 1 with pageSize 2
        p1, total = relevance_svc.get_relevant_jobs(remote=True, page=1, page_size=2)
        assert total == 3
        assert len(p1) == 2

        # Page 2 with pageSize 2 should return the remaining 1 item
        p2, total = relevance_svc.get_relevant_jobs(remote=True, page=2, page_size=2)
        assert total == 3
        assert len(p2) == 1


# ---------------------------------------------------------------------------
# Integration Tests: JobRepository.list_jobs
# ---------------------------------------------------------------------------

class TestJobRepositoryFiltering:
    """Test suite for JobRepository.list_jobs query composition."""

    def test_list_jobs_repo_all_filters(self):
        """Test JobRepository.list_jobs builds query correctly with all filters."""
        mock_client = MagicMock()
        mock_client.table.return_value = mock_client
        mock_client.select.return_value = mock_client
        mock_client.eq.return_value = mock_client
        mock_client.ilike.return_value = mock_client
        mock_client.order.return_value = mock_client
        mock_client.range.return_value = mock_client
        mock_client.execute.return_value = MagicMock(data=[{"id": "j1"}], count=1)

        repo = JobRepository(mock_client)
        jobs, total = repo.list_jobs(
            page=1,
            page_size=10,
            role="backend",
            location="bangalore",
            role_category="Software Engineering",
            company="Acme",
            remote=True,
            employment_type="Full-time",
            experience="Senior",
            sort="oldest",
        )

        assert total == 1
        assert len(jobs) == 1
        mock_client.table.assert_called_with("jobs")


# ---------------------------------------------------------------------------
# Integration Tests: FastAPI Endpoints (/jobs/search, /jobs, /jobs/personalized)
# ---------------------------------------------------------------------------

class TestJobApiFilteringEndpoints:
    """Test suite for HTTP API endpoints handling multi-parameter filters."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def mock_service(self):
        service = MagicMock()
        sample_jobs = create_sample_jobs()
        service.get_relevant_jobs.return_value = (sample_jobs[:2], len(sample_jobs))
        return service

    @pytest.fixture
    def override_deps(self, client, mock_service):
        app.dependency_overrides[get_job_relevance_service] = lambda: mock_service
        app.dependency_overrides[get_current_user] = lambda: MagicMock(user=MagicMock(id="user-123"))
        yield
        app.dependency_overrides.clear()

    def test_search_jobs_endpoint(self, client, mock_service, override_deps):
        """Test POST /jobs/search accepts all filter fields in JSON body."""
        payload = {
            "page": 1,
            "pageSize": 10,
            "role": "engineer",
            "location": "remote",
            "company": "Acme Corp",
            "skills": ["Python", "FastAPI"],
            "remote": True,
            "employmentType": "Full-time",
            "experience": "Senior",
            "sort": "newest",
        }
        response = client.post("/jobs/search", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data
        assert "meta" in data
        assert data["meta"]["total"] == 6

        # Verify service was called with correctly extracted kwargs
        mock_service.get_relevant_jobs.assert_called_once_with(
            user_id="user-123",
            page=1,
            page_size=10,
            role="engineer",
            location="remote",
            company="Acme Corp",
            skills=["Python", "FastAPI"],
            remote=True,
            employment_type="Full-time",
            experience="Senior",
            sort="newest",
        )

    def test_list_jobs_query_params(self, client, mock_service, override_deps):
        """Test GET /jobs passes query parameters to JobRelevanceService."""
        response = client.get(
            "/jobs?company=Acme&remote=true&employmentType=Full-time&sort=salary&page=2&page_size=5"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        mock_service.get_relevant_jobs.assert_called_once_with(
            user_id=None,
            page=2,
            page_size=5,
            role=None,
            location=None,
            company="Acme",
            skills=None,
            remote=True,
            employment_type="Full-time",
            experience=None,
            sort="salary",
        )

    def test_list_personalized_jobs_query_params(self, client, mock_service, override_deps):
        """Test GET /jobs/personalized passes filter parameters to JobRelevanceService."""
        response = client.get(
            "/jobs/personalized?company=Beta&remote=false&sort=newest&page=1&page_size=20"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        mock_service.get_relevant_jobs.assert_called_once_with(
            user_id="user-123",
            page=1,
            page_size=20,
            role=None,
            location=None,
            company="Beta",
            skills=None,
            remote=False,
            employment_type=None,
            experience=None,
            sort="newest",
        )
