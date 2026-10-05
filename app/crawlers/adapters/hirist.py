"""Hirist tech jobs crawler adapter.

Scrapes tech jobs from Hirist India, respecting Redis Token Bucket rate limiting.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
import httpx

from app.crawlers.base import BaseCrawler
from app.crawlers.models import CrawledJob
from app.crawlers.source_quality import stable_hash
from app.utils.rate_limiter import check_rate_limit

logger = logging.getLogger(__name__)

HIRIST_FEED_URL = "https://www.hirist.tech/api/job/feed"


class HiristAdapter(BaseCrawler):
    """Crawler adapter for Hirist India."""

    def __init__(
        self,
        query: str = "software engineer",
        location: str = "India",
        limit: int = 25,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.query = query
        self.location = location
        self.limit = limit
        self.timeout_seconds = timeout_seconds

    async def discover_jobs(self) -> list[CrawledJob]:
        """Fetch and normalize jobs from Hirist."""
        # 1. Rate limiter check: 5 requests per 10 seconds capacity
        allowed = await check_rate_limit("hirist", capacity=5, window_seconds=10)
        if not allowed:
            logger.warning("Hirist rate limit reached; deferring crawl.")
            return []

        jobs: list[CrawledJob] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        params = {
            "query": self.query,
            "loc": self.location,
            "size": min(self.limit, 50),
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get(HIRIST_FEED_URL, params=params, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("jobs", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    for item in items:
                        job = self._map_record(item)
                        if job:
                            jobs.append(job)
                else:
                    logger.info("Hirist feed returned status %s; fallback to empty", resp.status_code)
        except Exception as exc:
            logger.warning("Hirist crawl encountered error: %s", exc)

        return jobs

    def _map_record(self, raw: dict[str, Any]) -> Optional[CrawledJob]:
        title = str(raw.get("title") or raw.get("designation") or "").strip()
        if not title:
            return None

        company = str(raw.get("recruiter_name") or raw.get("company_name") or raw.get("company") or "").strip()
        ext_id = str(raw.get("id") or raw.get("job_id") or "")
        apply_url = str(raw.get("url") or raw.get("apply_url") or "")
        if apply_url and not apply_url.startswith("http"):
            apply_url = f"https://www.hirist.tech{apply_url}"

        if not ext_id:
            ext_id = f"hirist-{stable_hash(f'{title}|{company}|{apply_url}'.lower())}"

        skills = raw.get("skills") or raw.get("tags") or []
        if isinstance(skills, str):
            skills = [s.strip() for s in skills.split(",") if s.strip()]

        desc = str(raw.get("description") or raw.get("snippet") or title)

        return CrawledJob(
            title=title,
            company=company,
            description=desc,
            location=str(raw.get("location") or raw.get("city") or self.location).strip() or None,
            employment_type="Full Time",
            apply_url=apply_url or None,
            remote=bool("remote" in desc.lower() or "remote" in str(raw.get("location", "")).lower()),
            external_job_id=ext_id,
            source_platform="hirist",
            posted_date=str(raw.get("posted_date") or raw.get("created") or "") or None,
            skills=skills if isinstance(skills, list) else None,
            raw=raw,
        )
