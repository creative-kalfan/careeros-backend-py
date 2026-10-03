"""Greenhouse ATS adapter (port of GreenhouseAdapter.ts).

The board's ``location`` field is structured text (city / "N/A" / "US-Remote"
/ "IN-Bengaluru" ...), so India-relevance is deterministically identifiable
BEFORE persistence via :func:`app.services.jobs.india_geography.is_india_job`.

``india_only`` is an OPT-IN geographic filter: when True, only India-classified
postings are returned. The default (False) preserves the full board inventory
so foreign canonical jobs are never destroyed — the India-first boundary lives
at retrieval/ranking, not by deleting foreign rows.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import httpx

from app.crawlers.ats_http import get_json_response, request_semaphore, timeout_config
from app.crawlers.base import BaseCrawler
from app.crawlers.errors import BoardNotFoundError
from app.crawlers.models import CrawledJob
from app.crawlers.skills import KNOWN_SKILLS as _KNOWN_SKILLS
from app.crawlers.skills import extract_known_skills as _canonical_extract_skills
from app.services.jobs.india_geography import is_india_job

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def _coalesce(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def _is_remote(location: str) -> bool:
    return bool(re.search(r"remote", location, re.IGNORECASE))


def _extract_known_skills(text: str) -> list[str]:
    return _canonical_extract_skills(text)


def _extract_list(text: str, kind: str) -> list[str]:
    if not text:
        return []
    match = re.search(rf"{kind}[:\s]+([\s\S]*)", text, re.IGNORECASE)
    if not match:
        return []
    items = [i.strip() for i in re.split(r"\n|\.|;", match.group(1)) if i.strip()]
    return items[:8]


def _location_name(location: Any) -> Optional[str]:
    """Greenhouse location may be a string or a dict like {'name': ...}."""
    if isinstance(location, str):
        return location
    if isinstance(location, dict):
        name = location.get("name")
        return name if isinstance(name, str) else None
    return None


class GreenhouseAdapter(BaseCrawler):
    """Fetch and normalize jobs from a Greenhouse board."""

    def __init__(
        self,
        slug: str,
        api_base: str = GREENHOUSE_API,
        client: Optional[httpx.AsyncClient] = None,
        india_only: bool = False,
    ) -> None:
        self.slug = slug
        self.api_base = api_base
        self._client = client
        self.india_only = india_only
        self._semaphore = request_semaphore()

    async def __aenter__(self) -> "GreenhouseAdapter":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=timeout_config())
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def discover_jobs(self) -> list[CrawledJob]:
        url = self.api_base.format(slug=self.slug)
        client = self._client or httpx.AsyncClient(timeout=timeout_config())
        owned = self._client is None
        try:
            try:
                # Greenhouse supports ?content=true to return all jobs WITH full HTML description in one request
                async with self._semaphore:
                    response = await get_json_response(client,
                    url,
                    params={"content": "true"},
                    headers={"Accept": "application/json"},
                    )
            except httpx.HTTPError:
                raise
            if response.status_code == 404:
                raise BoardNotFoundError(f"Greenhouse board not found: {self.slug}")
            if response.status_code != 200:
                return []
            try:
                data = response.json()
            except ValueError:
                return []
            if not isinstance(data, dict):
                return []
            jobs_raw = data.get("jobs")
            if not isinstance(jobs_raw, list):
                return []

            # If jobs already have content (via content=true), parse directly!
            # Otherwise fall back to bounded detail fetch
            has_embedded_content = any(isinstance(j, dict) and j.get("content") for j in jobs_raw[:5])

            if has_embedded_content:
                jobs = [
                    self._parse_job(raw)
                    for raw in jobs_raw
                    if isinstance(raw, dict)
                ]
            else:
                async def _fetch_one(raw: dict[str, Any]) -> CrawledJob:
                    job_id = raw.get("id")
                    detail = raw
                    if job_id is not None:
                        async with self._semaphore:
                            detail = await self._fetch_detail(client, str(job_id))
                    if not isinstance(detail, dict):
                        detail = {}
                    merged = {**raw, **detail}
                    return self._parse_job(merged)

                jobs = list(
                    await asyncio.gather(
                        *(_fetch_one(raw) for raw in jobs_raw if isinstance(raw, dict))
                    )
                )

            if self.india_only:
                # Deterministic pre-ingestion geographic filter: keep only
                # postings whose location explicitly includes India. Never
                # rewrites or fabricates location data.
                jobs = [j for j in jobs if is_india_job(j.location, j.remote)]
            return list(jobs)
        finally:
            if owned and client is not None:
                await client.aclose()

    async def _fetch_detail(self, client: httpx.AsyncClient, job_id: str) -> dict | None:
        """Fetch full detail (with content) for a single job."""
        base = self.api_base.rstrip("/jobs").format(slug=self.slug)
        url = f"{base}/jobs/{job_id}"
        try:
            response = await get_json_response(client, url, headers={"Accept": "application/json"})
            if response.status_code != 200:
                return None
            data = response.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    def _parse_job(self, raw: dict[str, Any]) -> CrawledJob:
        content = str(raw.get("content") or raw.get("description") or "")
        location = _coalesce(_location_name(raw.get("location")), raw.get("location_name"))
        # Trustworthy posting timestamp: first_published is the original
        # publish date. Never use updated_at (recrawl would rewrite history).
        posted_date = _coalesce(raw.get("first_published"))
        return CrawledJob(
            title=str(raw.get("title") or ""),
            company=_coalesce(raw.get("company_name")) or "",
            description=content,
            location=location,
            employment_type=_coalesce(raw.get("employment_type"), raw.get("type")),
            apply_url=_coalesce(raw.get("absolute_url"), raw.get("url")),
            remote=_is_remote(str(location or "")),
            external_job_id=str(
                raw.get("id") if raw.get("id") is not None else raw.get("job_id") or ""
            ),
            source_platform="greenhouse",
            posted_date=posted_date,
            skills=_extract_known_skills(content),
            requirements=_extract_list(content, "requirements"),
            responsibilities=_extract_list(content, "responsibilities"),
            raw=raw,
        )
