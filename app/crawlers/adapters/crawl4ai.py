"""Crawl4AI career-page adapter (self-hosted generic crawl provider).

Discovers job postings on a company's official career page with a local
browser via Crawl4AI's async API — no third-party crawl credits. Shares
the deterministic parsing in :mod:`app.crawlers.adapters.career_page_parse`
with the Firecrawl adapter, so both generic providers produce identical
:class:`CrawledJob` shapes from the same HTML.

Boundaries (same as every other adapter):

- retrieval only: never touches Supabase, normalization, dedup, ARQ, or
  the job lifecycle — :class:`JobIngestionService` owns all of that.
- ``source_platform`` stays ``"firecrawl"`` (the generic career-page
  source family) so cross-provider dedup ``(source_platform,
  external_job_id)`` and not-seen deactivation keep working unchanged.
  The actual retrieval mechanism is recorded in ``raw["retrieval"]``.
- never calls an LLM; extraction is deterministic HTML parsing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional
from urllib.parse import urljoin

from parsel import Selector

from app.config import get_settings
from app.crawlers.adapters.career_page_parse import (
    _company_identity_from_html,
    _looks_like_job_url,
    parse_career_job_page,
)
from app.crawlers.base import BaseCrawler
from app.crawlers.models import CrawledJob

logger = logging.getLogger(__name__)


class Crawl4AIError(Exception):
    """Base error for Crawl4AI crawl failures (safe to surface/log)."""


class Crawl4AIConfigurationError(Crawl4AIError):
    """Crawl4AI is disabled, uninstalled, or has no usable browser."""


class Crawl4AITransientError(Crawl4AIError):
    """A transient crawl failure (timeout, browser hiccup) worth a fallback."""


# ponytail: one process-wide semaphore per limit value; per-URL throttles
# only if browser contention ever shows up in the crawl logs.
_SEMAPHORES: dict[int, asyncio.Semaphore] = {}


def _get_semaphore(limit: int) -> asyncio.Semaphore:
    """Process-wide browser-concurrency semaphore (asyncio-native)."""
    limit = max(1, int(limit))
    semaphore = _SEMAPHORES.get(limit)
    if semaphore is None:
        semaphore = asyncio.Semaphore(limit)
        _SEMAPHORES[limit] = semaphore
    return semaphore


def _links_from_result(result: Any, base_url: str) -> list[str]:
    """Candidate absolute job URLs from a Crawl4AI result (never raises)."""
    try:
        links = getattr(result, "links", None) or {}
        raw_links = (links.get("internal") or []) + (links.get("external") or [])
        out: list[str] = []
        for link in raw_links:
            href = link.get("href") if isinstance(link, dict) else getattr(link, "href", None)
            if not href:
                continue
            absolute = urljoin(base_url, str(href))
            if _looks_like_job_url(absolute) and absolute not in out:
                out.append(absolute)
        return out
    except Exception:
        return []


def _links_from_html(html: str, base_url: str) -> list[str]:
    """Fallback link harvest from raw HTML anchors (never raises)."""
    try:
        sel = Selector(text=html or "")
        out: list[str] = []
        seen: set[str] = set()
        for href in sel.xpath("//a/@href").getall():
            absolute = urljoin(base_url, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            if _looks_like_job_url(absolute):
                out.append(absolute)
        return out
    except Exception:
        return []


class Crawl4AIAdapter(BaseCrawler):
    """Crawl an official company career page with a local Crawl4AI browser."""

    def __init__(
        self,
        careers_url: str,
        company: Optional[str] = None,
        company_website: Optional[str] = None,
        max_pages: Optional[int] = None,
        crawler_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.careers_url = careers_url
        self.company = company
        self.company_website = company_website
        self._max_pages = (
            max_pages if max_pages is not None
            else get_settings().firecrawl_max_pages_per_crawl
        )
        # Injectable async-context-manager factory (tests pass a fake;
        # production lazily builds the real AsyncWebCrawler).
        self._crawler_factory = crawler_factory or self._default_crawler

    def _default_crawler(self) -> Any:
        from crawl4ai import AsyncWebCrawler
        from crawl4ai.async_configs import BrowserConfig

        return AsyncWebCrawler(config=BrowserConfig())

    def _run_config(self) -> Any:
        from crawl4ai.async_configs import CacheMode, CrawlerRunConfig

        return CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    async def _fetch(self, crawler: Any, url: str) -> Any:
        """Single page fetch under the browser semaphore + timeout."""
        settings = get_settings()
        timeout = float(settings.crawl4ai_timeout_seconds)
        async with _get_semaphore(int(settings.crawl4ai_max_concurrency)):
            return await asyncio.wait_for(
                crawler.arun(url=url, config=self._run_config()),
                timeout=timeout,
            )

    def _parse(self, url: str, html: str) -> Optional[CrawledJob]:
        return parse_career_job_page(
            url,
            html,
            company=self.company,
            careers_url=self.careers_url,
            company_website=self.company_website,
            retrieval="crawl4ai",
            source_platform="firecrawl",
        )

    async def discover_jobs(self) -> list[CrawledJob]:
        """Discover and extract job postings from the career page."""
        settings = get_settings()
        if not settings.crawl4ai_enabled:
            raise Crawl4AIConfigurationError(
                "CRAWL4AI_ENABLED is false; Crawl4AI crawling is unavailable."
            )
        try:
            self._run_config()
        except ImportError as exc:
            raise Crawl4AIConfigurationError(
                "crawl4ai package is not installed; Crawl4AI crawling is unavailable."
            ) from exc

        start = time.monotonic()
        try:
            async with self._crawler_factory() as crawler:
                return await self._discover_with(crawler, start)
        except Crawl4AIError:
            raise
        except asyncio.TimeoutError as exc:
            raise Crawl4AITransientError(f"Crawl4AI timed out for {self.careers_url}") from exc
        except Exception as exc:
            logger.warning(
                "crawler provider=crawl4ai url=%s success=false error=%s",
                self.careers_url, exc.__class__.__name__,
            )
            raise Crawl4AITransientError(f"Crawl4AI crawl failed: {exc.__class__.__name__}") from exc

    async def _discover_with(self, crawler: Any, start: float) -> list[CrawledJob]:
        try:
            page = await self._fetch(crawler, self.careers_url)
        except asyncio.TimeoutError as exc:
            raise Crawl4AITransientError(
                f"Crawl4AI timed out for {self.careers_url}"
            ) from exc
        if not getattr(page, "success", False):
            raise Crawl4AITransientError(
                f"Crawl4AI could not render {self.careers_url}: "
                f"{getattr(page, 'error_message', 'unknown')}"
            )

        html = getattr(page, "html", "") or ""
        identity = _company_identity_from_html(html, self.careers_url)
        candidates = _links_from_result(page, self.careers_url)
        if not candidates:
            candidates = _links_from_html(html, self.careers_url)
        candidates = candidates[: self._max_pages]

        if not candidates:
            logger.info(
                "crawler provider=crawl4ai url=%s success=true jobs=0 duration_ms=%d note=no-job-urls",
                self.careers_url, int((time.monotonic() - start) * 1000),
            )
            return []

        jobs: list[CrawledJob] = []
        for i, url in enumerate(candidates):
            if i > 0:
                await asyncio.sleep(0.5)
            try:
                detail = await self._fetch(crawler, url)
            except Exception as exc:
                # Per-page failure isolation: one bad page never kills the crawl.
                logger.warning(
                    "crawler provider=crawl4ai url=%s success=false error=%s detail=%s",
                    self.careers_url, exc.__class__.__name__, url,
                )
                continue
            if not getattr(detail, "success", False):
                continue
            crawled = self._parse(url, getattr(detail, "html", "") or "")
            if crawled is None:
                continue
            if identity:
                raw = dict(crawled.raw or {})
                if not self.company and identity.get("company_name"):
                    crawled.company = identity["company_name"]
                for key in ("logo_url", "favicon_url"):
                    if identity.get(key):
                        raw[key] = identity[key]
                crawled.raw = raw
            jobs.append(crawled)

        logger.info(
            "crawler provider=crawl4ai url=%s success=true jobs=%d duration_ms=%d discovered=%d",
            self.careers_url, len(jobs),
            int((time.monotonic() - start) * 1000), len(candidates),
        )
        return jobs
