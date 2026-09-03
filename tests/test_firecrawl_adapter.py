"""Tests for the Firecrawl career-page adapter (mocked client)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.crawlers.adapters.firecrawl import (
    FirecrawlAdapter,
    _extract_posted_date,
    _looks_like_job_url,
)
from app.crawlers.firecrawl_client import (
    FirecrawlClient,
    FirecrawlConfigurationError,
    FirecrawlError,
)

JOB_PAGE_HTML = """
<html><head><title>Backend Engineer - Acme</title></head><body>
<h1>Backend Engineer</h1>
<div>Location: Bengaluru, India</div>
<p>Build our platform. Full-time role posted on 12 Mar 2024.</p>
</body></html>
"""

CAREER_HTML = """
<html><head>
<meta property="og:site-name" content="Acme Corp"/>
<meta property="og:image" content="https://acme.com/logo.png"/>
<link rel="icon" href="/favicon.ico"/>
</head><body>
<a href="/jobs/backend-engineer">Backend Engineer</a>
<a href="/blog/thing">Blog</a>
</body></html>
"""


def _settings(api_key="k", max_pages=5):
    return type("S", (), {"firecrawl_api_key": api_key, "firecrawl_max_pages_per_crawl": max_pages})()


def _mock_fc(map_links=None, pages=None):
    fc = MagicMock(spec=FirecrawlClient)
    fc._api_key = "test-key"
    fc.map = AsyncMock(return_value=map_links or [])
    async def _scrape(url, formats=None):
        if pages is None or url not in pages:
            raise FirecrawlError("scrape failed")
        return pages[url]
    fc.scrape = AsyncMock(side_effect=_scrape)
    return fc


def test_url_heuristics():
    assert _looks_like_job_url("https://acme.com/jobs/backend-engineer")
    assert _looks_like_job_url("https://acme.com/careers/role-123456")
    assert not _looks_like_job_url("https://acme.com/blog/thing")
    assert not _looks_like_job_url("https://acme.com/about")


def test_posted_date_extraction():
    assert _extract_posted_date("posted 12 Mar 2024") == "2024-03-12T00:00:00+00:00"
    assert _extract_posted_date("since March 5, 2024") == "2024-03-05T00:00:00+00:00"
    assert _extract_posted_date("no date here") is None
    assert _extract_posted_date("") is None


@pytest.mark.asyncio
async def test_no_api_key_raises_configuration_error(monkeypatch):
    monkeypatch.setattr("app.crawlers.adapters.firecrawl.get_settings", lambda: _settings(api_key=""))
    adapter = FirecrawlAdapter("https://acme.com/careers", "Acme")
    with pytest.raises(FirecrawlConfigurationError):
        await adapter.discover_jobs()


@pytest.mark.asyncio
async def test_successful_discovery_with_provenance(monkeypatch):
    monkeypatch.setattr("app.crawlers.adapters.firecrawl.get_settings", lambda: _settings())
    job_url = "https://acme.com/jobs/backend-engineer"
    fc = _mock_fc(
        map_links=[job_url, "https://acme.com/blog/x"],
        pages={job_url: {"data": {"html": JOB_PAGE_HTML}}},
    )
    adapter = FirecrawlAdapter("https://acme.com/careers", "Acme Corp", client=fc)
    jobs = await adapter.discover_jobs()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Backend Engineer"
    assert job.company == "Acme Corp"
    assert job.apply_url == job_url
    assert job.location == "Bengaluru, India"
    assert job.employment_type == "Full-time"
    assert job.source_platform == "firecrawl"
    assert job.external_job_id
    assert job.posted_date == "2024-03-12T00:00:00+00:00"
    raw = job.raw
    assert raw["retrieval"] == "firecrawl"
    assert raw["canonical_url"] == job_url
    assert raw["careers_url"] == "https://acme.com/careers"
    assert raw["official_candidate"] is True


@pytest.mark.asyncio
async def test_fallback_to_career_page_and_identity(monkeypatch):
    monkeypatch.setattr("app.crawlers.adapters.firecrawl.get_settings", lambda: _settings())
    careers = "https://acme.com/careers"
    job_url = "https://acme.com/jobs/backend-engineer"

    fc = _mock_fc(map_links=[])  # map yields nothing -> fallback scrape

    def scrape_side_effect(url, formats=None):
        html = JOB_PAGE_HTML if url == job_url else CAREER_HTML
        return {"data": {"html": html}}

    fc.scrape = AsyncMock(side_effect=scrape_side_effect)

    adapter = FirecrawlAdapter(careers, "Acme", client=fc)
    jobs = await adapter.discover_jobs()
    assert len(jobs) == 1
    raw = jobs[0].raw
    assert raw["logo_url"] == "https://acme.com/logo.png"
    assert raw["favicon_url"] == "https://acme.com/favicon.ico"


@pytest.mark.asyncio
async def test_per_page_failure_isolation(monkeypatch):
    monkeypatch.setattr("app.crawlers.adapters.firecrawl.get_settings", lambda: _settings())
    ok = "https://acme.com/jobs/good"
    bad = "https://acme.com/jobs/bad"
    fc = _mock_fc(
        map_links=[ok, bad],
        pages={ok: {"data": {"html": JOB_PAGE_HTML}}},
    )
    adapter = FirecrawlAdapter("https://acme.com/careers", "Acme", client=fc)
    jobs = await adapter.discover_jobs()
    assert len(jobs) == 1
    assert jobs[0].apply_url == ok


@pytest.mark.asyncio
async def test_malformed_pages_are_skipped(monkeypatch):
    monkeypatch.setattr("app.crawlers.adapters.firecrawl.get_settings", lambda: _settings())
    url = "https://acme.com/jobs/1"
    fc = _mock_fc(map_links=[url], pages={url: {"data": {"html": "<html></html>"}}})
    adapter = FirecrawlAdapter("https://acme.com/careers", "Acme", client=fc)
    jobs = await adapter.discover_jobs()
    assert jobs == []


@pytest.mark.asyncio
async def test_partial_fields_are_kept_not_fabricated(monkeypatch):
    monkeypatch.setattr("app.crawlers.adapters.firecrawl.get_settings", lambda: _settings())
    url = "https://acme.com/jobs/1"
    fc = _mock_fc(map_links=[url], pages={url: {"data": {"html": "<html><h1>Engineer</h1></html>"}}})
    adapter = FirecrawlAdapter("https://acme.com/careers", "Acme", client=fc)
    jobs = await adapter.discover_jobs()
    assert len(jobs) == 1
    assert jobs[0].location is None
    assert jobs[0].posted_date is None
    assert jobs[0].employment_type is None

