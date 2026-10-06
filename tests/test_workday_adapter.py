"""Tests for Phase 2 Workday adapter, URL parsing, CxS API mapping, and Firecrawl cost control."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from app.crawlers.adapters.workday import (
    WorkdayCrawler,
    parse_workday_url,
    WORKDAY_DEFAULT_PAGE_SIZE,
)
from app.crawlers.models import CrawledJob
from app.services.jobs.crawl_dispatcher import dispatch_due_targets


def test_parse_workday_url():
    """Verify tenant, dc, and site parsing from various Workday career URL formats."""
    # Standard URL with locale
    assert parse_workday_url("https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced") == (
        "adobe", "wd5", "external_experienced"
    )
    # URL without locale
    assert parse_workday_url("https://target.wd1.myworkdayjobs.com/targetcareers") == (
        "target", "wd1", "targetcareers"
    )
    # Deep path with locale
    assert parse_workday_url("https://walmart.wd5.myworkdayjobs.com/en-US/WalmartExternal/job/123") == (
        "walmart", "wd5", "WalmartExternal"
    )
    # Non-workday URL
    assert parse_workday_url("https://careers.google.com/jobs") is None
    assert parse_workday_url("invalid-url") is None


def test_workday_crawler_from_slug():
    """Verify WorkdayCrawler constructor from slug."""
    crawler = WorkdayCrawler.from_slug("adobe|wd5|external_experienced")
    assert crawler.tenant == "adobe"
    assert crawler.dc == "wd5"
    assert crawler.site == "external_experienced"
    assert crawler.base_cxs_url == "https://adobe.wd5.myworkdayjobs.com/wday/cxs/adobe/external_experienced"

    with pytest.raises(ValueError, match="Workday slug must be 'tenant|dc|site'"):
        WorkdayCrawler.from_slug("adobe|wd5")


@pytest.mark.asyncio
async def test_workday_crawler_crawls_and_extracts_structured_start_date_only():
    """Verify crawler correctly parses list and detail, using ONLY structured startDate for posted_at."""
    crawler = WorkdayCrawler("adobe", "wd5", "external_experienced")

    mock_list_response = {
        "total": 1,
        "jobPostings": [
            {
                "title": "Staff Software Engineer",
                "externalPath": "/job/Bangalore/Staff-Software-Engineer_R12345",
                "locationsText": "Bangalore, India",
                "postedOn": "Posted 5 Days Ago",  # Must NOT be fabricated into posted_at!
                "bulletFields": ["R12345"],
            }
        ],
    }

    mock_detail_response = {
        "jobPostingInfo": {
            "id": "R12345",
            "title": "Staff Software Engineer",
            "jobDescription": "<div>We are looking for Python and FastAPI experts in India.</div>",
            "location": "Bangalore",
            "additionalLocations": ["Noida"],
            "startDate": "2026-10-01",  # Real authoritative ISO date
            "timeType": "Full time",
        }
    }

    with patch.object(crawler, "_post_json", new_callable=AsyncMock) as mock_post, \
         patch.object(crawler, "_get_json", new_callable=AsyncMock) as mock_get:

        mock_post.side_effect = [mock_list_response, {"total": 1, "jobPostings": []}]
        mock_get.return_value = mock_detail_response

        jobs = await crawler.crawl(max_details=10)

        assert len(jobs) == 1
        job = jobs[0]
        assert job.title == "Staff Software Engineer"
        assert job.company == "Adobe"
        assert "Bangalore" in job.location
        assert job.posted_date == "2026-10-01T00:00:00+00:00"
        assert job.external_job_id == "R12345"
        assert "python" in [s.lower() for s in job.skills]


@pytest.mark.asyncio
async def test_workday_crawler_detail_capping():
    """Verify detail calls are capped at max_details and remaining jobs still produce CrawledJob."""
    crawler = WorkdayCrawler("acme", "wd1", "careers")

    mock_list_response = {
        "total": 3,
        "jobPostings": [
            {"title": f"Job {i}", "externalPath": f"/job/path_{i}", "bulletFields": [f"ID_{i}"]}
            for i in range(3)
        ],
    }

    with patch.object(crawler, "_post_json", new_callable=AsyncMock) as mock_post, \
         patch.object(crawler, "_get_json", new_callable=AsyncMock) as mock_get:

        mock_post.side_effect = [mock_list_response, {"total": 3, "jobPostings": []}]
        mock_get.return_value = {"jobPostingInfo": {"startDate": "2026-10-01"}}

        # Cap details at 1
        jobs = await crawler.crawl(max_details=1)

        assert len(jobs) == 3
        # Exactly 1 detail call made
        assert mock_get.call_count == 1
        # Job 0 had detail fetched so it has posted_date
        assert jobs[0].posted_date is not None
        # Jobs 1 and 2 did not fetch detail; posted_date is None (never fabricated)
        assert jobs[1].posted_date is None
        assert jobs[2].posted_date is None


@pytest.mark.asyncio
async def test_firecrawl_cost_control_pauses_when_active_ats_exists():
    """Verify Firecrawl target is paused if an active ATS target exists for the same company."""
    ctx = {}
    rows = [{"source": "firecrawl", "slug": "PostHog|https://posthog.com/careers"}]

    mock_client = MagicMock()
    mock_update = MagicMock()
    mock_client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("app.services.jobs.crawl_dispatcher._migration_probe", return_value=True), \
         patch("app.services.jobs.crawl_dispatcher._worker_capacity", return_value=2), \
         patch("app.services.jobs.crawl_dispatcher._in_flight_crawls", new_callable=AsyncMock, return_value=0), \
         patch("app.services.jobs.crawl_dispatcher._rpc", return_value=rows), \
         patch("app.services.jobs.crawl_dispatcher.get_service_client", return_value=mock_client), \
         patch("app.workers.dispatcher.enqueue_scheduled_crawl", new_callable=AsyncMock) as mock_enqueue:

        enqueued = await dispatch_due_targets(ctx)

        # Firecrawl target paused because PostHog has active Ashby ATS target in registry
        assert enqueued == 0
        mock_enqueue.assert_not_called()
        mock_client.table().update.assert_called_with({"status": "paused", "last_error": "Paused: active validated ATS target exists (ashby:posthog)"})
