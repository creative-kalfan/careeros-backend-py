"""Tests for the JobRepository."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.table.return_value = client
    client.select.return_value = client
    client.eq.return_value = client
    client.execute.return_value = MagicMock(data=[], count=0)
    return client


@pytest.fixture
def job_repo(mock_client):
    return JobRepository(mock_client)


@pytest.mark.asyncio
async def test_upsert_jobs_new_job(job_repo, mock_client):
    """Test upserting a new job."""
    job = NormalizedJob(
        title="Test Job",
        company="Test Company",
        external_job_id="test-123",
        source_platform="test",
    )

    # Mock the existing check to return no existing job
    mock_client.table().select().eq().eq().execute.return_value = MagicMock(data=[])

    # Mock the insert
    mock_client.table().insert().execute.return_value = MagicMock(data=[{"id": "new-id"}])

    result = job_repo.upsert_jobs([job])

    assert result == {"inserted": 1, "updated": 0, "skipped": 0}
    mock_client.table().insert().execute.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_jobs_existing_job(job_repo, mock_client):
    """Test upserting an existing job."""
    job = NormalizedJob(
        title="Test Job",
        company="Test Company",
        external_job_id="test-123",
        source_platform="test",
    )

    # Mock the existing check to return an existing job
    mock_client.table().select().eq().eq().execute.return_value = MagicMock(
        data=[{"id": "existing-id"}]
    )

    # Mock the update
    mock_client.table().update().eq().execute.return_value = MagicMock(data=[{"id": "existing-id"}])

    result = job_repo.upsert_jobs([job])

    assert result == {"inserted": 0, "updated": 1, "skipped": 0}
    mock_client.table().update().eq().execute.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_jobs_missing_identity(job_repo, mock_client):
    """Test upserting a job with missing identity fields."""
    job = NormalizedJob(
        title="Test Job",
        company="Test Company",
    )

    result = job_repo.upsert_jobs([job])

    assert result == {"inserted": 0, "updated": 0, "skipped": 1}


@pytest.mark.asyncio
async def test_count_active(job_repo, mock_client):
    """Test counting active jobs."""
    mock_client.table().select().eq().execute.return_value = MagicMock(count=5)

    count = job_repo.count_active()

    assert count == 5
    mock_client.table().select().eq().execute.assert_called_once()


@pytest.mark.asyncio
async def test_list_jobs(job_repo, mock_client):
    """Test listing jobs with filters."""
    mock_client.table().select().eq().ilike().ilike().eq().order().range().execute.return_value = MagicMock(
        data=[{"id": "1"}], count=1
    )

    jobs, total = job_repo.list_jobs(
        page=1,
        page_size=10,
        role="engineer",
        location="remote",
        role_category="Software Engineering",
    )

    assert len(jobs) == 1
    assert total == 1


@pytest.mark.asyncio
async def test_get_job(job_repo, mock_client):
    """Test getting a single job."""
    mock_client.table().select().eq().eq().execute.return_value = MagicMock(
        data=[{"id": "1", "title": "Test Job"}]
    )

    job = job_repo.get_job("1")

    assert job is not None
    assert job["title"] == "Test Job"