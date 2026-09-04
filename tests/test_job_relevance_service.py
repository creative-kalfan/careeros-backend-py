"""Tests for the JobRelevanceService."""

import pytest
from unittest.mock import MagicMock

from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.services.jobs.job_relevance_service import JobRelevanceService


@pytest.fixture
def mock_job_repository():
    repo = MagicMock()
    repo.list_jobs.return_value = (
        [
            NormalizedJob(
                external_job_id="1",
                title="Software Engineer",
                company="Test Company",
                role_category="Software Engineering",
                skills=["python", "django"],
            ).model_dump()
        ],
        1,
    )
    repo.get_job.return_value = NormalizedJob(
        external_job_id="1",
        title="Software Engineer",
        company="Test Company",
        role_category="Software Engineering",
    ).model_dump()
    return repo


@pytest.fixture
def mock_profile_repository():
    repo = MagicMock()
    repo.get_profile.return_value = UserProfile(
        id="user-123",
        desired_role="Software Engineer",
        skills=["python", "django"],
    )
    return repo


@pytest.fixture
def mock_personalized_service():
    service = MagicMock()
    service.filter_jobs.return_value = [
        NormalizedJob(
            external_job_id="1",
            title="Software Engineer",
            company="Test Company",
            role_category="Software Engineering",
            match={
                "overall": 85,
                "skill_match": 90,
                "resume_match": 80,
                "experience_match": 85,
                "location_match": 90,
                "salary_match": 80,
                "company_preference": 100,
                "freshness": 90,
            }
        )
    ]
    service.calculate_match_score.return_value = {
        "overall": 85,
        "skill_match": 90,
        "resume_match": 80,
        "experience_match": 85,
        "location_match": 90,
        "salary_match": 80,
        "company_preference": 100,
        "freshness": 90,
    }
    return service


@pytest.fixture
def relevance_service(mock_job_repository, mock_profile_repository, mock_personalized_service):
    return JobRelevanceService(
        job_repository=mock_job_repository,
        profile_repository=mock_profile_repository,
        personalized_service=mock_personalized_service,
    )


def test_get_relevant_jobs_with_profile(relevance_service, mock_job_repository, mock_personalized_service):
    """Test getting relevant jobs with a user profile."""
    jobs, total = relevance_service.get_relevant_jobs(
        user_id="user-123",
        page=1,
        page_size=20,
        role="engineer",
        location="remote",
    )

    assert len(jobs) == 1
    assert total == 1
    mock_job_repository.list_jobs.assert_called_once()
    mock_personalized_service.filter_jobs.assert_called_once()
    mock_personalized_service.calculate_match_score.assert_called_once()


def test_get_relevant_jobs_without_profile(relevance_service, mock_job_repository, mock_personalized_service):
    """Test getting relevant jobs without a user profile."""
    mock_job = NormalizedJob(
        external_job_id="1",
        title="Software Engineer",
        company="Test Company",
        role_category="Software Engineering"
    )
    mock_job_repository.list_jobs.return_value = ([mock_job], 1)
    jobs, total = relevance_service.get_relevant_jobs(
        user_id=None,
        page=1,
        page_size=20,
        role="engineer",
        location="remote",
    )

    assert len(jobs) == 1
    assert total == 1
    assert jobs[0].external_job_id == "1"
    assert jobs[0].title == "Software Engineer"
    mock_job_repository.list_jobs.assert_called_once_with(
        page=1,
        page_size=1000,
        role="engineer",
        location="remote",
        role_category=None,
        company=None,
        remote=None,
        employment_type=None,
        experience=None,
        sort=None,
    )
    mock_personalized_service.filter_jobs.assert_not_called()
    mock_personalized_service.calculate_match_score.assert_not_called()


def test_get_job(relevance_service, mock_job_repository):
    """Test getting a single job."""
    job = relevance_service.get_job("1")

    assert job is not None
    assert job.title == "Software Engineer"
    mock_job_repository.get_job.assert_called_once_with("1")


def test_get_job_not_found(relevance_service, mock_job_repository):
    """Test getting a non-existent job."""
    mock_job_repository.get_job.return_value = None

    job = relevance_service.get_job("999")

    assert job is None
    mock_job_repository.get_job.assert_called_once_with("999")