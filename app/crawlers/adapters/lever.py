"""Lever ATS adapter."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import httpx

from app.crawlers.base import BaseCrawler
from app.crawlers.models import CrawledJob

LEVER_API = "https://api.lever.co/v0/postings/{slug}?mode=json"

_KNOWN_SKILLS = [
    "typescript", "javascript", "react", "next.js", "node", "python",
    "java", "sql", "postgresql", "aws", "docker", "kubernetes", "graphql",
    "rest", "agile", "leadership", "communication", "product", "figma",
    "tailwind", "supabase", "redis", "mongodb", "machine learning",
    "data analysis", "project management",
]

def _coalesce(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None

def _is_remote(location: str, workplace_type: str = "") -> bool:
    """Check if job is remote based on location or workplace type."""
    if workplace_type and re.search(r"remote", workplace_type, re.IGNORECASE):
        return True
    return bool(re.search(r"remote", location, re.IGNORECASE))

def _extract_known_skills(text: str) -> list[str]:
    normalized = text.lower()
    return [s for s in _KNOWN_SKILLS if s in normalized]

def _extract_list(text: str, kind: str) -> list[str]:
    if not text:
        return []
    match = re.search(rf"{kind}[:\s]+([\s\S]*)", text, re.IGNORECASE)
    if not match:
        return []
    items = [i.strip() for i in re.split(r"\n|\.|;", match.group(1)) if i.strip()]
    return items[:8]

def _location_name(location: Any) -> Optional[str]:
    """Lever location may be a string or a dict like {'name': ...}."""
    if isinstance(location, str):
        return location
    if isinstance(location, dict):
        name = location.get("name")
        return name if isinstance(name, str) else None
    return None

class LeverAdapter(BaseCrawler):
    """Fetch and normalize jobs from a Lever board."""

    def __init__(
        self,
        slug: str,
        api_base: str = LEVER_API,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.slug = slug
        self.api_base = api_base
        self._client = client

    async def __aenter__(self) -> "LeverAdapter":
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def discover_jobs(self) -> list[CrawledJob]:
        url = self.api_base.format(slug=self.slug)
        client = self._client or httpx.AsyncClient()
        owned = self._client is None
        try:
            try:
                response = await client.get(url, headers={"Accept": "application/json"})
            except httpx.HTTPError:
                return []
            if response.status_code == 404 or response.status_code != 200:
                return []
            try:
                data = response.json()
            except ValueError:
                return []
            if isinstance(data, list):
                jobs_raw = data
            elif isinstance(data, dict):
                jobs_raw = data.get("postings", [])
            else:
                return []

            # Bounded-concurrency detail fetch (limit 5, matching the TS
            # AshbyAdapter pattern — polite API consumer, not max speed).
            semaphore = asyncio.Semaphore(5)

            async def _fetch_one(raw: dict[str, Any]) -> CrawledJob:
                job_id = raw.get("id")
                detail = raw
                if job_id is not None:
                    async with semaphore:
                        detail = await self._fetch_detail(client, str(job_id))
                if not isinstance(detail, dict):
                    detail = {}
                merged = {**raw, **detail}
                return self._parse_job(merged)

            jobs = await asyncio.gather(
                *(_fetch_one(raw) for raw in jobs_raw if isinstance(raw, dict))
            )
            return list(jobs)
        except Exception as e:
            print(f"Error in discover_jobs: {e}")
            return []
        finally:
            if owned and client is not None:
                await client.aclose()

    async def _fetch_detail(self, client: httpx.AsyncClient, job_id: str) -> dict | None:
        """Fetch full detail (with content) for a single job."""
        base = self.api_base.rstrip("?mode=json").format(slug=self.slug)
        url = f"{base}/{job_id}"
        try:
            response = await client.get(url, headers={"Accept": "application/json"})
            if response.status_code != 200:
                return None
            data = response.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    def _parse_job(self, raw: dict[str, Any]) -> CrawledJob:
        # Lever API v0 returns: text (title), opening/openingPlain (description), 
        # descriptionBody/description, country, applyUrl/hostedUrl
        # Use 'description' field for full content (2534 chars) instead of truncated 'opening' (1200 chars)
        content = str(
            raw.get("description")
            or raw.get("descriptionBody")
            or raw.get("descriptionBodyPlain")
            or raw.get("opening")
            or raw.get("openingPlain")
            or raw.get("content")
            or ""
        )
        location = _coalesce(
            _location_name(raw.get("location")),
            raw.get("location_name"),
            raw.get("country"),
        )
        workplace_type = _coalesce(
            raw.get("workplaceType"),
            raw.get("employment_type"),
            raw.get("type"),
        )
        return CrawledJob(
            title=str(
                raw.get("text")
                or raw.get("title")
                or ""
            ),
            company=_coalesce(raw.get("company_name")) or self.slug,
            description=content,
            location=location,
            employment_type=workplace_type,
            workplace_type=workplace_type,
            apply_url=_coalesce(raw.get("applyUrl"), raw.get("hostedUrl"), raw.get("absolute_url"), raw.get("url")),
            remote=_is_remote(str(location or ""), str(workplace_type or "")),
            external_job_id=str(
                raw.get("id") if raw.get("id") is not None else raw.get("job_id") or ""
            ),
            source_platform="lever",
            skills=_extract_known_skills(content),
            requirements=_extract_list(content, "requirements"),
            responsibilities=_extract_list(content, "responsibilities"),
            raw=raw,
        )
