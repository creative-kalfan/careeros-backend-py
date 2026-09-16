"""Tests for Job Discovery 3.0: Multi-Source India Job Expansion."""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.crawlers.crawl_registry import (
    all_targets,
    targets_for_provider,
    targets_for_tier,
)
from app.crawlers.adapters.greenhouse import GreenhouseAdapter
from app.crawlers.adapters.firecrawl import FirecrawlAdapter
from app.crawlers.source_quality import detect_ats_provider, classify_source
from app.services.jobs.scheduled_crawl_runner import ScheduledCrawlRunner


def test_verified_company_registry_count_and_metadata():
    targets = all_targets()
    assert len(targets) >= 100, f"Expected >= 100 targets, got {len(targets)}"
    for t in targets:
        assert t.source in {'ashby', 'greenhouse', 'lever', 'smartrecruiters', 'firecrawl', 'ycombinator', 'adzuna', 'jobspy'}
        assert t.slug or t.source == 'ycombinator'
        assert t.provider in {'yc', 'firecrawl', 'ats', 'aggregator'}
        assert t.tier in {'P0', 'P1', 'P2'}
        assert t.priority in {1, 2, 3, 4}

    p0_count = len(targets_for_tier('P0'))
    p1_count = len(targets_for_tier('P1'))
    p2_count = len(targets_for_tier('P2'))
    assert p0_count >= 20
    assert p1_count >= 40
    assert p2_count >= 10



def test_ats_target_providers_distribution():
    ats = targets_for_provider('ats')
    sources = {t.source for t in ats}
    assert 'ashby' in sources
    assert 'greenhouse' in sources
    assert 'lever' in sources
    assert 'smartrecruiters' in sources

    ashby_count = sum(1 for t in ats if t.source == 'ashby')
    greenhouse_count = sum(1 for t in ats if t.source == 'greenhouse')
    lever_count = sum(1 for t in ats if t.source == 'lever')

    assert ashby_count >= 25
    assert greenhouse_count >= 50
    assert lever_count >= 5


@pytest.mark.asyncio
async def test_greenhouse_content_true_optimization():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jobs": [
            {
                "id": 101,
                "title": "Senior Backend Engineer",
                "company_name": "Databricks",
                "content": "<p>Build distributed lakehouse backend in Python/Scala.</p>",
                "location": {"name": "Bengaluru, India"},
                "absolute_url": "https://boards.greenhouse.io/databricks/jobs/101",
            }
        ]
    }
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    adapter = GreenhouseAdapter("databricks", client=mock_client)
    jobs = await adapter.discover_jobs()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior Backend Engineer"
    assert job.company == "Databricks"
    assert "distributed lakehouse" in job.description
    assert job.location == "Bengaluru, India"
    call_kwargs = mock_client.get.call_args.kwargs
    assert call_kwargs.get("params") == {"content": "true"}


@pytest.mark.asyncio
async def test_greenhouse_india_onny_filtering():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jobs": [
            {
                "id": 101,
                "title": "Software Engineer",
                "company_name": "Stripe",
                "content": "<p>Payments</p>",
                "location": {"name": "Bengaluru, India"},
                "absolute_url": "https://boards.greenhouse.io/stripe/jobs/101",
            },
            {
                "id": 102,
                "title": "Staff Engineer",
                "company_name": "Stripe",
                "content": "<p>Payments US</p>",
                "location": {"name": "San Francisco, CA+IND"},
                "absolute_url": "https://boards.greenhouse.io/stripe/jobs/102",
            },
        ]
    }
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    adapter = GreenhouseAdapter("stripe", client=mock_client, india_only=True)
    jobs = await adapter.discover_jobs()

    assert len(jobs) == 1
    assert jobs[0].external_job_id == "101"
    assert jobs[0].location == "Bengaluru, India"


@pytest.mark.asyncio
async def test_firecrawl_selective_enrichment():
    mock_fc = AsyncMock()
    mock_fc.scrape.return_value = {
        "data": {
            "html": "<html><body><h1>Lead Data Analyst</h1><p>Full-time role in Bangalore. Requirements: SQL, Python, Tableau.</p></body></html>",
            "markdown": "Lead Data Analyst. Full-time role in Bangalore.",
        }
    }

    adapter = FirecrawlAdapter("https://example.com/careers")
    adapter._client = mock_fc
    with pytest.MonkeyPatch.context() as mp:
        mock_settings = MagicMock()
        mock_settings.firecrawl_api_key = "test_fc_key"
        mp.setattr("app.crawlers.adapters.firecrawl.get_settings", lambda: mock_settings)

        enriched = await adapter.enrich_job("https://example.com/careers/lead-data-analyst")
        assert enriched.get("enriched_via") == "firecrawl"
        assert "Requirements: SQL, Python, Tableau" in enriched.get("description", "")
        assert enriched.get("employment_type") == "Full-time"


@pytest.mark.asyncio
async def test_scheduled_crawl_runner_tier_rotation():
    enqueued_targets = []

    async def mock_enqueue(source: str, slug: str):
        enqueued_targets.append((source, slug))

    runner = ScheduledCrawlRunner(enqueue_fn=mock_enqueue)
    await runner.run_provider_pass("ats", max_targets_per_pass=10)

    p0_ats = [t for t in targets_for_provider("ats") if t.tier == "P0"]
    for p0 in p0_ats:
        assert (p0.source, p0.slug) in enqueued_targets

    assert len(enqueued_targets) <= len(p0_ats) + 10

    # p1 or p2 target should also be present if others exist
    if len(enqueued_targets) > len(p0_ats):
        assert len(enqueued_targets) == len(p0_ats) + 10



def test_provider_provenance_and_ats_detection():
    ats_urls = [
        ("https://boards.greenhouse.io/stripe/jobs/123", "greenhouse"),
        ("https://jobs.ashbyhq.com/notion/456", "ashby"),
        ("https://jobs.lever.co/coupa/789", "lever"),
        ("https://jobs.smartrecruiters.com/ServiceNow/101112", "smartrecruiters"),
    ]
    for url, expected in ats_urls:
        detected = detect_ats_provider(url)
        assert detected == expected
        prov = classify_source(source_platform=expected, url=url, company="Company")
        assert prov.tier == 2
        assert prov.tier_label == "official_ats"
        assert prov.is_official is True
