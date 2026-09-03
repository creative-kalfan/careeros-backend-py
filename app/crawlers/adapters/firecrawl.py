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
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from parsel import Selector

from app.config import get_settings
from app.crawlers.base import BaseCrawler
from app.crawlers.firecrawl_client import (
    FirecrawlClient,
    FirecrawlConfigurationError,
    FirecrawlError,
)
from app.crawlers.models import CrawledJob
from app.crawlers.source_quality import (
    detect_ats_provider,
    is_aggregator_url,
    is_official_career_url,
    stable_hash,
)

logger = logging.getLogger(__name__)

# Path patterns that look like individual job postings.
_JOB_PATH_PATTERN = re.compile(
    r"/(?:job|jobs|career|careers|opening|position|requisition|role|vacancy)"
    r"|-[0-9]{4,}$|/\d{4,}(?:/|$)",
    re.IGNORECASE,
)

# Path patterns we never crawl (blogs, marketing, docs...).
_EXCLUDED_PATH_PATTERN = re.compile(
    r"/(?:blog|press|news|docs?|help|pricing|about|contact|legal|privacy|terms)"
    r"|\.pdf$|\.png$|\.jpg$|\.svg$|\.css$|\.js$",
    re.IGNORECASE,
)

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"

_POSTED_PATTERN = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTHS})[a-z]*\s+(\d{{4}})\b"
    rf"|({_MONTHS})[a-z]*\s+(\d{{1,2}}),?\s+(\d{{4}})",
    re.IGNORECASE,
)


def _looks_like_job_url(url: str) -> bool:
    """Heuristic filter for candidate job-detail URLs."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    path = parsed.path or "/"
    if _EXCLUDED_PATH_PATTERN.search(path):
        return False
    return bool(_JOB_PATH_PATTERN.search(path))


def _extract_posted_date(text: str) -> Optional[str]:
    """Best-effort ISO date extraction ('12 Mar 2024' / 'Mar 12, 2024').

    Returns None when no reliable date is present — never fabricated.
    """
    if not text:
        return None
    match = _POSTED_PATTERN.search(text[:4000])
    if not match:
        return None
    month_map = {m: i + 1 for i, m in enumerate(_MONTHS.split("|"))}
    groups = match.groups()
    try:
        if groups[0]:  # 12 Mar 2024
            day, mon, year = int(groups[0]), month_map[groups[1].lower()[:3]], int(groups[2])
        else:  # Mar 12, 2024
            mon, day, year = month_map[groups[3].lower()[:3]], int(groups[4]), int(groups[5])
        return datetime(year, mon, day, tzinfo=timezone.utc).isoformat()
    except (KeyError, ValueError):
        return None


def _company_identity_from_html(html: str, page_url: str) -> dict[str, Any]:
    """Extract company identity/logo metadata from a career page.

    Priority: official logo (og:image on the official domain) → favicon.
    No logos are generated; only real assets found on the page are reported.
    """
    identity: dict[str, Any] = {}
    if not html:
        return identity
    sel = Selector(text=html)
    site_name = sel.xpath("//meta[@property='og:site-name']/@content").get()
    if site_name and site_name.strip():
        identity["company_name"] = site_name.strip()
    og_image = sel.xpath("//meta[@property='og:image']/@content").get()
    if og_image and og_image.strip():
        identity["logo_url"] = urljoin(page_url, og_image.strip())
    favicon = sel.xpath(
        "//link[@rel='icon' or @rel='shortcut icon' or @rel='apple-touch-icon']/@href"
    ).get()
    if favicon and favicon.strip():
        identity["favicon_url"] = urljoin(page_url, favicon.strip())
    return identity


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
        if not html:
            return None
        sel = Selector(text=html)
        title = None
        for xpath in ("//h1//text()", "//h2//text()", "//title//text()"):
            for value in sel.xpath(xpath).getall():
                value = (value or "").strip()
                if len(value) >= 3:
                    title = value
                    break
            if title:
                break
        if not title:
            return None

        location = None
        for token in sel.xpath(
            "//div[contains(., 'Location')]//text() | //span[contains(@class,'location')]//text()"
        ).getall():
            token = (token or "").strip()
            if not token or len(token) > 80:
                continue
            if token.lower().startswith("location"):
                remainder = token.split(":", 1)[-1].strip()
                if remainder:
                    location = remainder
                    break
                continue  # bare 'Location' label
            if "Location" not in token:
                location = token
                break

        description = " ".join(
            t.strip() for t in sel.xpath("//p//text()").getall() if t and t.strip()
        )[:6000] or title

        employment_type = None
        for label in ("Full-time", "Part-time", "Contract", "Internship", "Temporary"):
            if label.lower() in (title + " " + description).lower():
                employment_type = label
                break

        remote = "remote" in (title + " " + (location or "")).lower() or None
        posted_date = _extract_posted_date(description)

        raw: dict[str, Any] = {
            "retrieval": "firecrawl",
            "careers_url": self.careers_url,
            "company_website": self.company_website,
            "canonical_url": url,
            "discovered_url": url,
            "source_domain": urlparse(url).hostname,
            "official_candidate": is_official_career_url(url, self.company, self.careers_url),
            "ats_provider": detect_ats_provider(url),
            "aggregator": is_aggregator_url(url),
            "first_discovered_at": datetime.now(timezone.utc).isoformat(),
        }

        return CrawledJob(
            title=title,
            company=self.company or "",
            description=description,
            location=location,
            employment_type=employment_type,
            remote=remote,
            posted_date=posted_date,
            apply_url=url,
            skills=[],
            external_job_id=stable_hash(url),
            source_platform="firecrawl",
            raw=raw,
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

