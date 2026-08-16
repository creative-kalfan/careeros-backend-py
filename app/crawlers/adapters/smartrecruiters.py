"""SmartRecruiters ATS adapter."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import httpx

from app.crawlers.base import BaseCrawler
from app.crawlers.models import CrawledJob

SMARTRECRUITERS_API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"


def _coalesce(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def _is_remote(remote: Any, location: str = "") -> bool:
    """Check if job is remote based on explicit SmartRecruiters fields."""
    if isinstance(remote, bool):
        return remote
    if isinstance(remote, str):
        return bool(re.search(r"remote", remote, re.IGNORECASE))
    if location and re.search(r"remote", location, re.IGNORECASE):
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


class SmartRecruitersAdapter(BaseCrawler):
    """Fetch and normalize jobs from a SmartRecruiters job board."""

    def __init__(
        self,
        slug: str,
        api_base: str = SMARTRECRUITERS_API,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.slug = slug
        self.api_base = api_base
        self._client = client

    async def __aenter__(self) -> "SmartRecruitersAdapter":
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
            jobs_raw = data.get("content", [])
            if not isinstance(jobs_raw, list):
                return []

            # List endpoint has minimal data - fetch full details for each job
            # with bounded concurrency (limit 5)
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
        """Fetch full detail (with jobAd content) for a single job."""
        url = f"https://api.smartrecruiters.com/v1/companies/{self.slug}/postings/{job_id}"
        try:
            response = await client.get(url, headers={"Accept": "application/json"})
            if response.status_code != 200:
                return None
            data = response.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    def _parse_job(self, raw: dict[str, Any]) -> CrawledJob:
        # SmartRecruiters detail endpoint provides jobAd.sections with full content.
        # Extract description from jobAd.sections.jobDescription.text (not 'content')
        content = ""
        job_ad = raw.get("jobAd", {})
        if isinstance(job_ad, dict):
            sections = job_ad.get("sections", {})
            if isinstance(sections, dict):
                job_desc = sections.get("jobDescription", {})
                if isinstance(job_desc, dict):
                    content = str(job_desc.get("text", "") or "")
        
        # Fallback to simple description field if present
        if not content:
            content = str(raw.get("description") or raw.get("jobDescription") or "")

        # Extract location
        location = ""
        loc = raw.get("location")
        if isinstance(loc, dict):
            location = _coalesce(
                loc.get("fullLocation"),
                loc.get("city"),
                loc.get("region"),
                loc.get("country"),
            )
        location = location or _coalesce(raw.get("location"), raw.get("city"))

        # Extract employment type
        emp_type = raw.get("typeOfEmployment")
        if isinstance(emp_type, dict):
            employment_type = emp_type.get("label", "")
        else:
            employment_type = _coalesce(raw.get("employmentType"), raw.get("type"))

        # Extract company name
        company = raw.get("company")
        if isinstance(company, dict):
            company_name = company.get("name", "")
        else:
            company_name = _coalesce(raw.get("companyName"), raw.get("company"))

        return CrawledJob(
            title=str(raw.get("name") or raw.get("title") or ""),
            company=company_name or self.slug.replace("-", " ").title(),
            description=content,
            location=location,
            employment_type=employment_type,
            apply_url=_coalesce(raw.get("applyUrl"), raw.get("postingUrl"), raw.get("url")),
            remote=_is_remote(raw.get("location", {}).get("remote") if isinstance(raw.get("location"), dict) else None, str(location or "")),
            external_job_id=str(raw.get("id") or ""),
            source_platform="smartrecruiters",
            skills=_extract_known_skills(content),
            requirements=_extract_list(content, "requirements"),
            responsibilities=_extract_list(content, "responsibilities"),
            raw=raw,
        )