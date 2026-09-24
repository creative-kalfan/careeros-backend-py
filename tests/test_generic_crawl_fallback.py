"""Tests for Crawl4AI primary + Firecrawl fallback + 429 circuit breaker.

All provider I/O is mocked — no real network, no real browser.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.crawlers.adapters.crawl4ai import (
    Crawl4AIAdapter,
    Crawl4AIConfigurationError,
    Crawl4AITransientError,
)
from app.crawlers.firecrawl_client import FirecrawlRateLimitError
from app.crawlers.generic_fallback import (
    FirecrawlCircuitBreaker,
    ProviderOutcome,
    classify_firecrawl_error,
    crawl_generic_career_page,
    reset_firecrawl_breaker,
)
from app.crawlers.models import CrawledJob

JOB_HTML = """
<html><head><title>Backend Engineer - Acme</title></head><body>
<h1>Backend Engineer</h1>
<div>Location: Bengaluru, India</div>
<p>Build our platform. Full-time role.</p>
</body></html>
"""

CAREERS_HTML = """
<html><head>
<meta property="og:site-name" content="Acme Corp"/>
<meta property="og:image" content="https://acme.com/logo.png"/>
</head><body>
<a href="/jobs/backend-engineer">Backend Engineer</a>
<a href="/blog/thing">Blog</a>
</body></html>
"""

CAREERS_URL = "https://acme.com/careers"
JOB_URL = "https://acme.com/jobs/backend-engineer"


def _settings(enabled: bool = True, concurrency: int = 2):
    return SimpleNamespace(
        crawl4ai_enabled=enabled,
        crawl4ai_max_concurrency=concurrency,
        crawl4ai_timeout_seconds=5.0,
        firecrawl_api_key="k",
        firecrawl_max_pages_per_crawl=5,
        firecrawl_circuit_cooldown_seconds=300.0,
    )


class _FakeResult:
    def __init__(self, html: str = "", links: Any = None, success: bool = True):
        self.html = html
        self.links = links or {"internal": [], "external": []}
        self.success = success
        self.error_message = "" if success else "render failed"


class _FakeCrawler:
    """Async-context-manager stand-in for AsyncWebCrawler."""

    def __init__(self, pages: dict[str, _FakeResult] | None = None):
        self.pages = pages or {}
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def arun(self, url: str, config: Any = None):
        self.calls.append(url)
        if url not in self.pages:
            raise RuntimeError("fetch failed")
        return self.pages[url]


def _career_pages(job_html: str = JOB_HTML) -> dict[str, _FakeResult]:
    return {
        CAREERS_URL: _FakeResult(
            html=CAREERS_HTML,
            links={"internal": [{"href": "/jobs/backend-engineer"}], "external": []},
        ),
        JOB_URL: _FakeResult(html=job_html),
    }


@pytest.fixture(autouse=True)
def _clean_breaker():
    reset_firecrawl_breaker()
    yield
    reset_firecrawl_breaker()


def _patch_settings(monkeypatch, enabled: bool = True, concurrency: int = 2):
    settings = _settings(enabled, concurrency)
    monkeypatch.setattr("app.crawlers.adapters.crawl4ai.get_settings", lambda: settings)
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    return settings


# A. Basic adapter behavior -------------------------------------------------

@pytest.mark.asyncio
async def test_crawl4ai_success_produces_crawled_jobs(monkeypatch):
    _patch_settings(monkeypatch)
    adapter = Crawl4AIAdapter(
        CAREERS_URL, "Acme", crawler_factory=lambda: _FakeCrawler(_career_pages())
    )
    jobs = await adapter.discover_jobs()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Backend Engineer"
    assert job.apply_url == JOB_URL
    assert job.location == "Bengaluru, India"
    assert job.source_platform == "firecrawl"  # generic family identity
    assert job.raw["retrieval"] == "crawl4ai"
    assert job.raw["careers_url"] == CAREERS_URL
    assert job.raw["logo_url"] == "https://acme.com/logo.png"


@pytest.mark.asyncio
async def test_crawl4ai_disabled_raises_config_error(monkeypatch):
    _patch_settings(monkeypatch, enabled=False)
    adapter = Crawl4AIAdapter(CAREERS_URL, "Acme")
    with pytest.raises(Crawl4AIConfigurationError):
        await adapter.discover_jobs()


# B. Crawl4AI failure -------------------------------------------------------

@pytest.mark.asyncio
async def test_crawl4ai_failure_is_classified_transient(monkeypatch):
    _patch_settings(monkeypatch)

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("browser gone")

        async def __aexit__(self, *exc):
            return False

    adapter = Crawl4AIAdapter(CAREERS_URL, "Acme", crawler_factory=_Boom)
    with pytest.raises(Crawl4AITransientError):
        await adapter.discover_jobs()


# C. Crawl4AI → Firecrawl fallback ------------------------------------------

def _canned_firecrawl_jobs() -> list[CrawledJob]:
    return [CrawledJob(title="T", company="Acme", description="d",
                       external_job_id="x", source_platform="firecrawl")]


@pytest.mark.asyncio
async def test_fallback_order_and_single_persistence(monkeypatch):
    _patch_settings(monkeypatch)
    order: list[str] = []

    async def _fail(self) -> list[CrawledJob]:
        order.append("crawl4ai")
        raise Crawl4AITransientError("render failed")

    async def _succeed(self) -> list[CrawledJob]:
        order.append("firecrawl")
        return _canned_firecrawl_jobs()

    monkeypatch.setattr(Crawl4AIAdapter, "discover_jobs", _fail)
    from app.crawlers.adapters.firecrawl import FirecrawlAdapter

    monkeypatch.setattr(FirecrawlAdapter, "discover_jobs", _succeed)

    from app.services.jobs.job_ingestion_service import JobIngestionService

    calls: list[list] = []

    class _FakeRepo:
        def upsert_jobs(self, jobs: list) -> dict[str, int]:
            calls.append(list(jobs))
            return {"discovered": 1, "inserted": 1, "updated": 0,
                    "unchanged": 0, "deduplicated": 0, "skipped": 0}

    ingestion = JobIngestionService(job_repository=_FakeRepo())
    result = await ingestion.ingest_generic_career_page(CAREERS_URL, company="Acme")

    assert order == ["crawl4ai", "firecrawl"]  # primary first, fallback second
    assert result["inserted"] == 1
    assert result["provider"] == "firecrawl"
    assert len(calls) == 1  # persistence occurs exactly once


# D. Firecrawl 429 ----------------------------------------------------------

@pytest.mark.asyncio
async def test_firecrawl_429_is_rate_limited_without_retry_storm(monkeypatch):
    _patch_settings(monkeypatch)
    firecrawl_calls: list[str] = []

    async def _fail(self) -> list[CrawledJob]:
        raise Crawl4AITransientError("render failed")

    async def _limited(self) -> list[CrawledJob]:
        firecrawl_calls.append(self.careers_url)
        raise FirecrawlRateLimitError("Firecrawl rate limited (429) after 4 attempts")

    monkeypatch.setattr(Crawl4AIAdapter, "discover_jobs", _fail)
    from app.crawlers.adapters.firecrawl import FirecrawlAdapter

    monkeypatch.setattr(FirecrawlAdapter, "discover_jobs", _limited)

    jobs, meta = await crawl_generic_career_page(CAREERS_URL, company="Acme")

    assert jobs == []
    assert meta["firecrawl_outcome"] == ProviderOutcome.RATE_LIMITED.value
    assert len(firecrawl_calls) == 1  # one attempt, no immediate retry loop

    # Storm prevention: the very next crawl skips Firecrawl entirely.
    jobs2, meta2 = await crawl_generic_career_page(CAREERS_URL, company="Acme")
    assert jobs2 == []
    assert meta2["firecrawl_skipped_by_circuit"] is True
    assert len(firecrawl_calls) == 1

    assert classify_firecrawl_error(
        FirecrawlRateLimitError("429")) == ProviderOutcome.RATE_LIMITED


# E. Circuit breaker ---------------------------------------------------------

def test_breaker_opens_skips_then_probes():
    now = [1000.0]
    breaker = FirecrawlCircuitBreaker(
        cooldown_seconds=300.0, monotonic=lambda: now[0]
    )
    assert not breaker.should_skip()

    breaker.record_rate_limited()
    assert breaker.is_open and breaker.should_skip()

    now[0] += 299.0
    assert breaker.should_skip()  # still cooling down

    now[0] += 2.0
    assert not breaker.should_skip()  # cooldown over → probe allowed

    breaker.record_success()
    assert not breaker.is_open

    breaker.record_rate_limited()
    first_cooldown = breaker.cooldown_until
    now[0] += 10.0
    breaker.record_rate_limited()
    assert breaker.cooldown_until > first_cooldown  # 429 extends cooldown


# F. Crawl4AI concurrency -----------------------------------------------------

@pytest.mark.asyncio
async def test_browser_concurrency_is_bounded(monkeypatch):
    _patch_settings(monkeypatch, concurrency=2)
    state = {"current": 0, "peak": 0}

    class _SlowCrawler(_FakeCrawler):
        async def arun(self, url: str, config: Any = None):
            state["current"] += 1
            state["peak"] = max(state["peak"], state["current"])
            try:
                await asyncio.sleep(0.02)
                return await super().arun(url, config)
            finally:
                state["current"] -= 1

    pages = _career_pages()
    adapters = [
        Crawl4AIAdapter(CAREERS_URL, "Acme", crawler_factory=lambda: _SlowCrawler(pages))
        for _ in range(5)
    ]
    results = await asyncio.gather(*(a.discover_jobs() for a in adapters))
    assert all(len(r) == 1 for r in results)
    assert state["peak"] <= 2


# G. Existing ingestion contract ------------------------------------------------

@pytest.mark.asyncio
async def test_generic_ingest_uses_canonical_pipeline(monkeypatch):
    _patch_settings(monkeypatch)
    canned = [CrawledJob(title="T", company="Acme", description="d",
                         external_job_id="x", source_platform="firecrawl")]

    async def _ok(self) -> list[CrawledJob]:
        return list(canned)

    monkeypatch.setattr(Crawl4AIAdapter, "discover_jobs", _ok)

    from app.services.jobs.job_ingestion_service import JobIngestionService

    seen: list = []
    upserts: list[list] = []

    class _FakeRepo:
        def upsert_jobs(self, jobs: list) -> dict[str, int]:
            upserts.append(list(jobs))
            return {"discovered": len(jobs), "inserted": len(jobs), "updated": 0,
                    "unchanged": 0, "deduplicated": 0, "skipped": 0}

    class _SpyService:
        from app.services.jobs.job_service import JobService as _Real
        _real = _Real()

        def normalize_and_classify(self, job: CrawledJob):
            seen.append(job)
            return self._real.normalize_and_classify(job)

    ingestion = JobIngestionService(job_repository=_FakeRepo(), job_service=_SpyService())
    main_thread = threading.get_ident()
    result = await ingestion.ingest_generic_career_page(CAREERS_URL, company="Acme")

    assert len(seen) == 1  # normalize_and_classify used
    assert len(upserts) == 1 and len(upserts[0]) == 1  # _persist_offloop once
    assert upserts[0][0].title == "T"  # normalized job persisted
    assert result["provider"] == "crawl4ai"


# H. Event-loop responsiveness ---------------------------------------------------

@pytest.mark.asyncio
async def test_crawler_does_not_block_event_loop(monkeypatch):
    _patch_settings(monkeypatch)
    ticks = [0]

    async def _heartbeat():
        while True:
            ticks[0] += 1
            await asyncio.sleep(0.005)

    class _SleepyCrawler(_FakeCrawler):
        async def arun(self, url: str, config: Any = None):
            await asyncio.sleep(0.03)  # browser I/O must yield to the loop
            return await super().arun(url, config)

    adapter = Crawl4AIAdapter(
        CAREERS_URL, "Acme", crawler_factory=lambda: _SleepyCrawler(_career_pages())
    )
    beat = asyncio.create_task(_heartbeat())
    try:
        jobs = await adapter.discover_jobs()
    finally:
        beat.cancel()
        try:
            await beat
        except asyncio.CancelledError:
            pass

    assert len(jobs) == 1
    assert ticks[0] > 0  # loop stayed responsive throughout the crawl
