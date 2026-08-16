"""Tests for Adzuna aggregator adapter."""

import os
from pathlib import Path
import pytest
from dotenv import load_dotenv
from unittest.mock import AsyncMock, MagicMock

from app.crawlers.aggregators.adzuna import AdzunaAdapter
from app.crawlers.models import CrawledJob

# Load .env from backend root so ADZUNA creds are available in tests
_backend_root = Path(__file__).resolve().parent.parent
load_dotenv(_backend_root / ".env")


@pytest.mark.asyncio
async def test_adzuna_adapter_real_search():
    """Test real Adzuna search with credentials."""
    app_id = os.getenv("ADZUNA_APP_ID", "")
    app_key = os.getenv("ADZUNA_APP_KEY", "")
    
    if not app_id or not app_key:
        pytest.skip("Adzuna credentials not configured")
    
    async with AdzunaAdapter(app_id=app_id, app_key=app_key) as adapter:
        jobs = await adapter.search_by_query("software engineer", results_per_page=5)
    
    assert isinstance(jobs, list)
    assert len(jobs) > 0, "Expected jobs from Adzuna search"
    
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
        print(f"Salary: {job.salary}")
        print(f"Posted Date: {job.posted_date}")
        print(f"Skills: {job.skills[:5]}")
        
        assert job.title, "Title should not be empty"
        assert job.company, "Company should not be empty"
        assert job.description, "Description should not be empty"
        assert job.source_platform == "adzuna"
        assert job.external_job_id, "External job ID should not be empty"


@pytest.mark.asyncio
async def test_adzuna_adapter_multiple_queries():
    """Test real Adzuna search for multiple keywords."""
    app_id = os.getenv("ADZUNA_APP_ID", "")
    app_key = os.getenv("ADZUNA_APP_KEY", "")
    
    if not app_id or not app_key:
        pytest.skip("Adzuna credentials not configured")
    
    queries = ["software engineer", "data scientist"]
    
    for query in queries:
        async with AdzunaAdapter(app_id=app_id, app_key=app_key) as adapter:
            jobs = await adapter.search_by_query(query, results_per_page=3)
        
        print(f"\nQuery: {query} -> {len(jobs)} jobs")
        assert isinstance(jobs, list)
        assert len(jobs) > 0, f"Expected jobs for query: {query}"


@pytest.mark.asyncio
async def test_adzuna_adapter_no_credentials(monkeypatch):
    """Test that missing credentials returns empty list."""
    # Ensure no creds in env for this test
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    async with AdzunaAdapter(app_id="", app_key="") as adapter:
        jobs = await adapter.search_by_query("software engineer")
    
    assert isinstance(jobs, list)
    assert len(jobs) == 0


@pytest.mark.asyncio
async def test_adzuna_adapter_mocked():
    """Test with mocked HTTP response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {
                "id": "test-job-1",
                "title": "Software Engineer",
                "company": {"display_name": "Test Company"},
                "location": {"display_name": "San Francisco, CA"},
                "description": "We are looking for a Software Engineer with Python skills.",
                "salary_min": 100000,
                "salary_max": 150000,
                "salary_currency": "USD",
                "contract_type": "permanent",
                "created": "2026-01-01T00:00:00Z",
                "redirect_url": "https://adzuna.com/jobs/test-job-1",
            }
        ]
    }
    
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    
    async with AdzunaAdapter(app_id="test-id", app_key="test-key", client=mock_client) as adapter:
        jobs = await adapter.search_by_query("software engineer")
    
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Software Engineer"
    assert job.company == "Test Company"
    assert job.location == "San Francisco, CA"
    assert "Software Engineer" in job.description
    assert job.employment_type == "permanent"
    assert job.remote is False
    assert job.apply_url == "https://adzuna.com/jobs/test-job-1"
    assert job.external_job_id == "test-job-1"
    assert job.source_platform == "adzuna"
    assert job.salary == "100000 - 150000 USD"
    assert job.posted_date == "2026-01-01T00:00:00Z"