"""Workday ATS adapter via public CxS JSON API.

Architecture:
  - List endpoint: POST https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
  - Detail endpoint: GET https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}
  - Slug format: "{tenant}|{dc}|{site}" (e.g. "adobe|wd5|external_experienced")
  - Concurrency <= 3 per tenant, polite jittered delay, 5s connect / 20s read timeouts.
  - Date rule: posted_at ONLY from structured 'startDate' (ISO date). Never parse relative "Posted X Days Ago".
  - Detail capping: only fetch detail for new/changed items, capped per crawl by WORKDAY_MAX_DETAILS_PER_CRAWL (default 50).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.crawlers.base import BaseCrawler
from app.crawlers.errors import BoardNotFoundError
from app.crawlers.models import CrawledJob
from app.crawlers.skills import extract_known_skills
from app.services.jobs.india_geography import is_india_job

logger = logging.getLogger(__name__)

# Default polite limits
WORKDAY_DEFAULT_PAGE_SIZE = 20
WORKDAY_MAX_PAGE_SIZE = 50
WORKDAY_MAX_DETAILS_PER_CRAWL = 50
WORKDAY_CONNECT_TIMEOUT = 5.0
WORKDAY_READ_TIMEOUT = 20.0
WORKDAY_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Host-level semaphore cache: tenant -> Semaphore(3)
_TENANT_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def _get_tenant_semaphore(tenant: str) -> asyncio.Semaphore:
    if tenant not in _TENANT_SEMAPHORES:
        _TENANT_SEMAPHORES[tenant] = asyncio.Semaphore(3)
    return _TENANT_SEMAPHORES[tenant]


def parse_workday_url(url: str) -> Optional[tuple[str, str, str]]:
    """Parse tenant, datacenter (wdN), and site from a careers URL.
    
    Example:
      https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced -> ("adobe", "wd5", "external_experienced")
      https://target.wd1.myworkdayjobs.com/targetcareers -> ("target", "wd1", "targetcareers")
    """
    try:
        parsed = urlparse(url)
        host_match = re.match(r"^([^.]+)\.(wd\d+)\.myworkdayjobs\.com$", parsed.netloc.lower())
        if not host_match:
            return None
        tenant, dc = host_match.groups()
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if not parts:
            return None
        # Discard locale prefix if present (e.g. en-US)
        if len(parts) > 1 and re.match(r"^[a-z]{2}(-[A-Z]{2})?$", parts[0]):
            site = parts[1]
        else:
            site = parts[0]
        return (tenant, dc, site)
    except Exception:
        return None


class WorkdayCrawler(BaseCrawler):
    """Crawler adapter for Workday CxS public endpoints."""

    def __init__(self, tenant: str, dc: str, site: str) -> None:
        self.tenant = tenant.strip().lower()
        self.dc = dc.strip().lower()
        self.site = site.strip()
        self.origin = f"https://{self.tenant}.{self.dc}.myworkdayjobs.com"
        self.base_cxs_url = f"{self.origin}/wday/cxs/{self.tenant}/{self.site}"
        self.semaphore = _get_tenant_semaphore(self.tenant)

    @classmethod
    def from_slug(cls, slug: str) -> WorkdayCrawler:
        """Construct from slug format '{tenant}|{dc}|{site}'."""
        parts = slug.split("|")
        if len(parts) < 3:
            raise ValueError(f"Workday slug must be 'tenant|dc|site', got '{slug}'")
        return cls(parts[0], parts[1], parts[2])

    async def _post_json(self, client: httpx.AsyncClient, url: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST with politeness retry, jitter, and error classification."""
        for attempt in range(3):
            async with self.semaphore:
                try:
                    response = await client.post(
                        url,
                        json=body,
                        headers={"Content-Type": "application/json", "User-Agent": WORKDAY_USER_AGENT},
                    )
                    if response.status_code == 404:
                        raise BoardNotFoundError(f"Workday site not found: {url}")
                    if response.status_code == 429:
                        retry_after = float(response.headers.get("Retry-After", 1.0))
                        await asyncio.sleep(retry_after + random.uniform(0.5, 1.5))
                        continue
                    if response.status_code >= 500:
                        if attempt == 2:
                            response.raise_for_status()
                        await asyncio.sleep(0.5 * (2**attempt) + random.uniform(0.1, 0.5))
                        continue
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        raise BoardNotFoundError(f"Workday site not found: {url}") from exc
                    if attempt == 2:
                        raise
                except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError):
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1.0 + random.uniform(0.1, 0.5))
        return {}

    async def _get_json(self, client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        """GET job detail with politeness."""
        for attempt in range(3):
            async with self.semaphore:
                try:
                    response = await client.get(
                        url,
                        headers={"Content-Type": "application/json", "User-Agent": WORKDAY_USER_AGENT},
                    )
                    if response.status_code == 404:
                        return {}
                    if response.status_code == 429:
                        retry_after = float(response.headers.get("Retry-After", 1.0))
                        await asyncio.sleep(retry_after + random.uniform(0.5, 1.5))
                        continue
                    response.raise_for_status()
                    return response.json()
                except Exception:
                    if attempt == 2:
                        return {}
                    await asyncio.sleep(0.5 * (2**attempt))
        return {}

    async def crawl(
        self,
        max_details: int = WORKDAY_MAX_DETAILS_PER_CRAWL,
        india_only: bool = False,
    ) -> list[CrawledJob]:
        """Crawl job listings and fetch capped details."""
        list_url = f"{self.base_cxs_url}/jobs"
        timeout = httpx.Timeout(WORKDAY_READ_TIMEOUT, connect=WORKDAY_CONNECT_TIMEOUT)

        discovered_postings: list[dict[str, Any]] = []
        offset = 0
        limit = WORKDAY_DEFAULT_PAGE_SIZE

        async with httpx.AsyncClient(timeout=timeout) as client:
            # 1. Paginate list endpoint
            while True:
                body = {
                    "appliedFacets": {},
                    "limit": limit,
                    "offset": offset,
                    "searchText": "",
                }
                data = await self._post_json(client, list_url, body)
                postings = data.get("jobPostings", [])
                total = int(data.get("total", 0))

                if not postings:
                    break

                discovered_postings.extend(postings)
                offset += len(postings)

                # Check if we fetched all or hit Workday cap
                if offset >= total or len(discovered_postings) >= 2000:
                    if total > 2000:
                        logger.warning(
                            "Workday %s total %d exceeds 2000 cap; pagination truncated",
                            self.tenant, total
                        )
                    break

                # Jittered delay between pages
                await asyncio.sleep(random.uniform(0.1, 0.3))

            logger.info(
                "Workday list phase completed for %s:%s. Discovered %d jobs (total reported=%d)",
                self.tenant, self.site, len(discovered_postings), total
            )

            # 2. Fetch details for a bounded batch of postings
            jobs: list[CrawledJob] = []
            details_fetched = 0

            for posting in discovered_postings:
                ext_path = posting.get("externalPath")
                if not ext_path:
                    continue

                title = posting.get("title") or "Unknown"
                locations_text = posting.get("locationsText") or ""
                bullet_fields = posting.get("bulletFields") or []
                req_id = bullet_fields[0] if bullet_fields else ""
                
                # Public web job URL
                canonical_url = f"{self.origin}/en-US/{self.site}{ext_path}"

                # Decide if we should fetch detail
                detail_info: dict[str, Any] = {}
                if details_fetched < max_details:
                    detail_url = f"{self.base_cxs_url}{ext_path}"
                    detail_res = await self._get_json(client, detail_url)
                    detail_info = detail_res.get("jobPostingInfo", {})
                    if detail_info:
                        details_fetched += 1
                        await asyncio.sleep(random.uniform(0.1, 0.25))

                # Extract posted_at: ONLY from structured startDate (e.g. "2026-10-05")
                posted_at: Optional[datetime] = None
                raw_start_date = detail_info.get("startDate")
                if raw_start_date:
                    try:
                        parsed_date = datetime.fromisoformat(str(raw_start_date))
                        posted_at = parsed_date.replace(tzinfo=timezone.utc) if parsed_date.tzinfo is None else parsed_date
                    except Exception:
                        posted_at = None

                description = detail_info.get("jobDescription") or ""
                location = detail_info.get("location") or locations_text or "Remote"
                additional_locs = detail_info.get("additionalLocations", [])
                if additional_locs and isinstance(additional_locs, list):
                    location = f"{location}; " + "; ".join(str(l) for l in additional_locs[:3])

                time_type = detail_info.get("timeType") or ""
                employment_type = "full-time" if "full" in time_type.lower() else ("part-time" if "part" in time_type.lower() else "full-time")
                external_id = detail_info.get("jobReqId") or req_id or ext_path.split("_")[-1] or ext_path

                is_india = is_india_job(location) or is_india_job(description)
                if india_only and not is_india:
                    continue

                skills = extract_known_skills(description) if description else []

                jobs.append(
                    CrawledJob(
                        title=title,
                        company=self.tenant.replace("-", " ").title(),
                        location=location,
                        description=description,
                        apply_url=canonical_url,
                        posted_date=posted_at.isoformat() if posted_at else None,
                        source_platform="workday",
                        external_job_id=str(external_id),
                        remote="remote" in location.lower() or "remote" in title.lower(),
                        employment_type=employment_type,
                        skills=skills,
                    )
                )

            return jobs

    async def discover_jobs(self) -> list[CrawledJob]:
        """BaseCrawler interface implementation."""
        return await self.crawl()
