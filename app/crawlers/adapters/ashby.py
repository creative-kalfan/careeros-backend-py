"""Ashby ATS adapter."""

from __future__ import annotations

import re
from typing import Any, Optional

import httpx

from app.crawlers.base import BaseCrawler
from app.crawlers.models import CrawledJob

ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _coalesce(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def _is_remote(is_remote: Any, workplace_type: str = "") -> bool:
    """Check if job is remote based on explicit Ashby fields."""
    if isinstance(is_remote, bool):
        return is_remote
    if isinstance(is_remote, str):
        return bool(re.search(r"remote", is_remote, re.IGNORECASE))
    if workplace_type and re.search(r"remote", workplace_type, re.IGNORECASE):
        return True
    return False


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


_KNOWN_SKILLS = [
    "typescript", "javascript", "react", "next.js", "node", "python",
    "java", "sql", "postgresql", "aws", "docker", "kubernetes", "graphql",
    "rest", "agile", "leadership", "communication", "product", "figma",
    "tailwind", "supabase", "redis", "mongodb", "machine learning",
    "data analysis", "project management",
]


class AshbyAdapter(BaseCrawler):
    """Fetch and normalize jobs from an Ashby job board."""

    def __init__(
        self,
        slug: str,
        api_base: str = ASHBY_API,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.slug = slug
        self.api_base = api_base
        self._client = client

    async def __aenter__(self) -> "AshbyAdapter":
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
            if response.status_code != 200:
                return []
            try:
                data = response.json()
            except ValueError:
                return []
            if not isinstance(data, dict):
                return []
            jobs_raw = data.get("jobs", [])
            if not isinstance(jobs_raw, list):
                return []

            # The list endpoint already includes full descriptionHtml,
            # so no per-job detail fetch is needed.
            jobs = [self._parse_job(raw) for raw in jobs_raw if isinstance(raw, dict)]
            return jobs
        except Exception as e:
            print(f"Error in discover_jobs: {e}")
            return []
        finally:
            if owned and client is not None:
                await client.aclose()

    def _parse_job(self, raw: dict[str, Any]) -> CrawledJob:
        # Ashby list endpoint provides descriptionHtml with full content.
        # Fall back to description if present, otherwise empty string.
        content = str(
            raw.get("descriptionHtml")
            or raw.get("description")
            or raw.get("content")
            or ""
        )
        location = _coalesce(
            raw.get("location"),
            raw.get("locationName"),
        )
        if isinstance(raw.get("address"), dict):
            postal = raw["address"].get("postalAddress", {})
            location = _coalesce(
                location,
                postal.get("addressLocality"),
                postal.get("addressRegion"),
                postal.get("addressCountry"),
            )
        employment_type = _coalesce(
            raw.get("employmentType"),
            raw.get("type"),
        )
        workplace_type = _coalesce(
            raw.get("workplaceType"),
            raw.get("employmentType"),
            raw.get("type"),
        )
        return CrawledJob(
            title=str(raw.get("title") or ""),
            company=self.slug.replace("-", " ").title(),
            description=content,
            location=location,
            employment_type=employment_type,
            workplace_type=workplace_type,
            apply_url=_coalesce(raw.get("applyUrl"), raw.get("jobUrl")),
            remote=_is_remote(raw.get("isRemote"), str(workplace_type or "")),
            external_job_id=str(raw.get("id") or ""),
            source_platform="ashby",
            skills=_extract_known_skills(content),
            requirements=_extract_list(content, "requirements"),
            responsibilities=_extract_list(content, "responsibilities"),
            raw=raw,
        )