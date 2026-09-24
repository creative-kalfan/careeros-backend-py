"""Firecrawl career-page adapter.

Discovers job postings on a company's official career page via Firecrawl:
map the site to find candidate job URLs, scrape each bounded page, parse it
into a :class:`CrawledJob`, and attach full source provenance in ``raw``.

Firecrawl is a RETRIEVAL mechanism only — official-source classification is
performed by :mod:`app.crawlers.source_quality` based on the resulting URL
domain, never on the fact that Firecrawl was used.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin

from parsel import Selector

from app.config import get_settings
from app.crawlers.base import BaseCrawler
from app.crawlers.adapters.career_page_parse import (
    _company_identity_from_html,
    _extract_posted_date,
    _looks_like_job_url,
    parse_career_job_page,
)
from app.crawlers.firecrawl_client import (
    FirecrawlClient,
    FirecrawlConfigurationError,
    FirecrawlError,
)
from app.crawlers.models import CrawledJob

logger = logging.getLogger(__name__)

# Re-exported for backwards compatibility (tests import these from here).
__all__ = [
    "FirecrawlAdapter",
    "_looks_like_job_url",
    "_extract_posted_date",
    "_company_identity_from_html",
    "parse_career_job_page",
]


class FirecrawlAdapter(BaseCrawler):
    """Crawl an official company career page via Firecrawl."""

    def __init__(
        self,
        careers_url: str,
        company: Optional[str] = None,
        company_website: Optional[str] = None,
        client: Optional[FirecrawlClient] = None,
        max_pages: Optional[int] = None,
    ) -> None:
        self.careers_url = careers_url
        self.company = company
        self.company_website = company_website
        self._client = client
        self._max_pages = max_pages if max_pages is not None else get_settings().firecrawl_max_pages_per_crawl

    def _fc(self) -> FirecrawlClient:
        if self._client is None:
            self._client = FirecrawlClient()
        return self._client

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def _discover_job_urls(self) -> tuple[list[str], dict[str, Any]]:
        """Find candidate job URLs; fall back to scraping the careers page."""
        identity: dict[str, Any] = {}
        fc = self._fc()
        try:
            links = await fc.map(self.careers_url, limit=200)
        except FirecrawlError as exc:
            logger.warning("Firecrawl map failed for %s: %s", self.careers_url, exc.__class__.__name__)
            links = []

        candidates = [link for link in links if _looks_like_job_url(link)][: self._max_pages]

        if not candidates:
            # Fallback: scrape the career page itself and extract listing links.
            try:
                page = await fc.scrape(self.careers_url, formats=["html"])
                html = ((page.get("data") or {}).get("html")) or ""
            except FirecrawlError as exc:
                logger.warning("Firecrawl scrape failed for %s: %s", self.careers_url, exc.__class__.__name__)
                return [], identity

            identity.update(_company_identity_from_html(html, self.careers_url))
            if html:
                sel = Selector(text=html)
                seen: set[str] = set()
                for href in sel.xpath("//a/@href").getall():
                    absolute = urljoin(self.careers_url, href)
                    if absolute in seen:
                        continue
                    seen.add(absolute)
                    if _looks_like_job_url(absolute):
                        candidates.append(absolute)
                    if len(candidates) >= self._max_pages:
                        break
        return candidates[: self._max_pages], identity

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def _parse_job_page(self, url: str, html: str) -> Optional[CrawledJob]:
        """Parse one job page into a CrawledJob (None when not a job page)."""
        return parse_career_job_page(
            url,
            html,
            company=self.company,
            careers_url=self.careers_url,
            company_website=self.company_website,
            retrieval="firecrawl",
            source_platform="firecrawl",
        )

    async def discover_jobs(self) -> list[CrawledJob]:
        """Discover and extract job postings from the official career page."""
        settings = get_settings()
        configured_key = getattr(self._client, "_api_key", "") if self._client else ""
        if not settings.firecrawl_api_key and not configured_key:
            raise FirecrawlConfigurationError(
                "FIRECRAWL_API_KEY is not configured; Firecrawl crawling is unavailable."
            )

        job_urls, identity = await self._discover_job_urls()
        if not job_urls:
            logger.info("Firecrawl: no job URLs discovered for %s", self.careers_url)
            return []

        fc = self._fc()
        jobs: list[CrawledJob] = []
        for i, url in enumerate(job_urls):
            if i > 0:
                await asyncio.sleep(1.0)
            try:
                page = await fc.scrape(url, formats=["html"])
            except FirecrawlError as exc:
                # Per-page failure isolation: one bad page never kills the crawl.
                logger.warning("Firecrawl scrape failed for %s: %s", url, exc.__class__.__name__)
                continue
            html = ((page.get("data") or {}).get("html")) or ""
            crawled = self._parse_job_page(url, html)
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
            "Firecrawl: discovered=%d extracted=%d for %s",
            len(job_urls), len(jobs), self.careers_url,
        )
        return jobs

    async def enrich_job(self, apply_url: str) -> dict[str, Any]:
        """Selectively enrich a thin job posting via single-page scrape.

        Retrieves missing description, skills, workplace type, and posted date.
        Returns extracted fields dict (or empty dict on failure/unconfigured).
        One page scrape only — strict request-budget preservation.
        """
        settings = get_settings()
        configured_key = getattr(self._client, "_api_key", "") if self._client else ""
        if not settings.firecrawl_api_key and not configured_key:
            return {}

        fc = self._fc()
        try:
            page = await fc.scrape(apply_url, formats=["html", "markdown"])
        except FirecrawlError as exc:
            logger.warning("Firecrawl enrichment scrape failed for %s: %s", apply_url, exc)
            return {}

        data = page.get("data") or {}
        html = data.get("html") or ""
        markdown = data.get("markdown") or ""

        parsed = self._parse_job_page(apply_url, html)
        if not parsed:
            # Fallback to markdown text if HTML selector didn't catch title
            return {"description": markdown[:6000]} if markdown else {}

        return {
            "description": parsed.description or markdown[:6000],
            "employment_type": parsed.employment_type,
            "remote": parsed.remote,
            "posted_date": parsed.posted_date,
            "skills": parsed.skills,
            "enriched_via": "firecrawl",
            "enriched_at": datetime.now(timezone.utc).isoformat(),
        }

