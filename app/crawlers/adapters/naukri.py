"""Naukri crawler adapter.

Scrapes high-demand tech jobs from Naukri India.
Protected against bot detection: uses Firecrawl when available, falls back to Playwright headless browser,
and enforces Redis Token Bucket rate limiting.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
from urllib.parse import quote_plus
from parsel import Selector

from app.config import get_settings
from app.crawlers.base import BaseCrawler
from app.crawlers.firecrawl_client import FirecrawlClient
from app.crawlers.models import CrawledJob
from app.crawlers.source_quality import stable_hash
from app.utils.rate_limiter import check_rate_limit

logger = logging.getLogger(__name__)

NAUKRI_SEARCH_BASE = "https://www.naukri.com/{query}-jobs-in-{location}"


class NaukriAdapter(BaseCrawler):
    """Crawler adapter for Naukri India with Firecrawl & Playwright integration."""

    def __init__(
        self,
        query: str = "software-engineer",
        location: str = "india",
        limit: int = 20,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.query = query.lower().replace(" ", "-")
        self.location = location.lower().replace(" ", "-")
        self.limit = limit
        self.timeout_seconds = timeout_seconds

    @property
    def target_url(self) -> str:
        return NAUKRI_SEARCH_BASE.format(query=self.query, location=self.location)

    async def discover_jobs(self) -> list[CrawledJob]:
        """Fetch and normalize jobs from Naukri with rate limiting and fallback."""
        # 1. Rate limiting check: max 2 requests per 10s window to protect IP
        allowed = await check_rate_limit("naukri", capacity=2, window_seconds=10)
        if not allowed:
            logger.warning("Naukri rate limit reached; deferring crawl.")
            return []

        settings = get_settings()
        html_content = ""

        # 2. Strategy 1: Firecrawl
        if settings.firecrawl_api_key:
            try:
                logger.info("Attempting Naukri scrape via Firecrawl: %s", self.target_url)
                async with FirecrawlClient() as client:
                    scrape_res = await asyncio.wait_for(
                        client.scrape(self.target_url, formats=["html"]),
                        timeout=self.timeout_seconds,
                    )
                    data = scrape_res.get("data") or {}
                    html_content = data.get("html") or ""
            except Exception as exc:
                logger.warning("Naukri Firecrawl scrape failed: %s; falling back to Playwright", exc)

        # 3. Strategy 2: Playwright fallback
        if not html_content:
            try:
                html_content = await self._scrape_with_playwright()
            except Exception as exc:
                logger.warning("Naukri Playwright scrape failed: %s", exc)

        if not html_content:
            logger.warning("No HTML retrieved for Naukri (%s)", self.target_url)
            return []

        return self._parse_naukri_html(html_content)

    async def _scrape_with_playwright(self) -> str:
        """Playwright headless browser scraper for heavily protected sites."""
        from playwright.async_api import async_playwright

        logger.info("Scraping Naukri via Playwright: %s", self.target_url)
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            try:
                await page.goto(self.target_url, wait_until="domcontentloaded", timeout=int(self.timeout_seconds * 1000))
                # Wait briefly for dynamic elements
                await page.wait_for_timeout(2000)
                content = await page.content()
                return content
            finally:
                await browser.close()

    def _parse_naukri_html(self, html: str) -> list[CrawledJob]:
        """Extract job listings from Naukri search results HTML."""
        sel = Selector(text=html)
        jobs: list[CrawledJob] = []

        # Naukri job cards typically use 'article.jobTuple', 'div.srp-jobtuple-wrapper', or 'div.cust-job-tuple'
        cards = sel.css("div.srp-jobtuple-wrapper, div.cust-job-tuple, article.jobTuple")
        for card in cards[:self.limit]:
            title = card.css("a.title::text, a[data-testid='job-title']::text").get()
            if not title:
                continue
            title = title.strip()

            company = card.css("a.comp-name::text, a.subTitle::text, a[data-testid='company-name']::text").get()
            company = company.strip() if company else "Unknown Company"

            apply_url = card.css("a.title::attr(href), a[data-testid='job-title']::attr(href)").get()
            if apply_url and not apply_url.startswith("http"):
                apply_url = f"https://www.naukri.com{apply_url}"

            location = card.css("span.loc-wrap::text, span.locWdth::text, span[data-testid='job-location']::text").get()
            location = location.strip() if location else "India"

            desc = card.css("span.job-desc::text, div.job-description::text").get()
            desc = desc.strip() if desc else f"{title} at {company}"

            skill_tags = card.css("ul.tags-gt li::text, ul.tags li::text").getall()
            skills = [s.strip() for s in skill_tags if s.strip()]

            ext_id = f"naukri-{stable_hash(f'{title}|{company}|{apply_url or location}'.lower())}"

            jobs.append(
                CrawledJob(
                    title=title,
                    company=company,
                    description=desc,
                    location=location,
                    employment_type="Full Time",
                    apply_url=apply_url or None,
                    remote=bool("remote" in location.lower() or "remote" in desc.lower()),
                    external_job_id=ext_id,
                    source_platform="naukri",
                    posted_date=None,
                    skills=skills or None,
                    raw={"source": "naukri", "title": title, "company": company, "url": apply_url},
                )
            )

        return jobs
