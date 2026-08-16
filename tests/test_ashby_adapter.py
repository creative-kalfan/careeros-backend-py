"""Tests for Ashby ATS adapter."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.crawlers.adapters.ashby import AshbyAdapter
from app.crawlers.models import CrawledJob


@pytest.mark.asyncio
async def test_ashby_adapter_real_api():
    """Test against real Notion Ashby board."""
    async with AshbyAdapter("notion") as adapter:
        jobs = await adapter.discover_jobs()
    
    assert isinstance(jobs, list)
    assert len(jobs) > 0, "Expected jobs from Notion's Ashby board"
    
    # Inspect first 3 jobs for quality
    for job in jobs[:3]:
        print(f"\n=== Sample Job ===")
        print(f"Title: {job.title}")
        print(f"Company: {job.company}")
        print(f"Location: {job.location}")
        print(f"Employment Type: {job.employment_type}")
        print(f"Remote: {job.remote}")
        print(f"Description length: {len(job.description)}")
        print(f"Apply URL: {job.apply_url}")
        print(f"External Job ID: {job.external_job_id}")
        print(f"Skills: {job.skills[:5]}")
        
        assert job.title, "Title should not be empty"
        assert job.description, "Description should not be empty"
        assert len(job.description) > 100, f"Description too short: {len(job.description)} chars"
        assert job.source_platform == "ashby"
        assert job.external_job_id, "External job ID should not be empty"


@pytest.mark.asyncio
async def test_ashby_adapter_invalid_slug():
    """Test that invalid slug returns empty list, not exception."""
    async with AshbyAdapter("this-slug-definitely-does-not-exist-12345") as adapter:
        jobs = await adapter.discover_jobs()
    
    assert isinstance(jobs, list)
    assert len(jobs) == 0


@pytest.mark.asyncio
async def test_ashby_adapter_remote_detection():
    """Test remote detection with real data from Notion."""
    async with AshbyAdapter("notion") as adapter:
        jobs = await adapter.discover_jobs()
    
    assert len(jobs) > 0, "Need jobs to verify remote detection"
    
    # Find at least one remote and one non-remote job
    remote_jobs = [j for j in jobs if j.remote]
    non_remote_jobs = [j for j in jobs if not j.remote]
    
    print(f"\nRemote jobs: {len(remote_jobs)}")
    print(f"Non-remote jobs: {len(non_remote_jobs)}")
    
    # Show samples
    if remote_jobs:
        job = remote_jobs[0]
        print(f"\nRemote job example:")
        print(f"  Title: {job.title}")
        print(f"  Location: {job.location}")
        print(f"  Employment Type: {job.employment_type}")
        print(f"  Remote: {job.remote}")
    
    if non_remote_jobs:
        job = non_remote_jobs[0]
        print(f"\nNon-remote job example:")
        print(f"  Title: {job.title}")
        print(f"  Location: {job.location}")
        print(f"  Employment Type: {job.employment_type}")
        print(f"  Remote: {job.remote}")
    
    # We expect at least some remote jobs from Notion
    assert len(remote_jobs) > 0, "Expected at least one remote job from Notion"


@pytest.mark.asyncio
async def test_ashby_adapter_mocked():
    """Test with mocked HTTP response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "jobs": [
            {
                "id": "test-job-1",
                "title": "Software Engineer",
                "descriptionHtml": "<p>We are looking for a <strong>Software Engineer</strong>.</p>",
                "location": "San Francisco, CA",
                "employmentType": "FullTime",
                "workplaceType": "Remote",
                "isRemote": True,
                "applyUrl": "https://jobs.ashbyhq.com/test-company/test-job-1",
                "jobUrl": "https://jobs.ashbyhq.com/test-company/test-job-1",
            }
        ]
    }
    
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    
    async with AshbyAdapter("test-company", client=mock_client) as adapter:
        jobs = await adapter.discover_jobs()
    
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Software Engineer"
    assert job.company == "Test Company"
    assert "Software Engineer" in job.description
    assert job.location == "San Francisco, CA"
    assert job.employment_type == "FullTime"
    assert job.remote is True
    assert job.apply_url == "https://jobs.ashbyhq.com/test-company/test-job-1"
    assert job.external_job_id == "test-job-1"
    assert job.source_platform == "ashby"