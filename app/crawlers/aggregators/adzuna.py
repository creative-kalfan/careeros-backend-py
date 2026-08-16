"""Adzuna aggregator adapter."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Optional

import httpx

from app.crawlers.base import BaseCrawler
from app.crawlers.models import CrawledJob

logger = logging.getLogger(__name__)

ADZUNA_API = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
ADZUNA_RETRY_BASE_DELAY = 2.0
ADZUNA_RETRY_MAX_ATTEMPTS = 3


def _coalesce(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def _is_remote(location: str) -> bool:
    """Check if job is remote based on location text."""
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


_KNOWN_SKILLS = [
    "typescript", "javascript", "react", "next.js", "node", "python",
    "java", "sql", "postgresql", "aws", "docker", "kubernetes", "graphql",
    "rest", "agile", "leadership", "communication", "product", "figma",
    "tailwind", "supabase", "redis", "mongodb", "machine learning",
    "data analysis", "project management",
]


class AdzunaAdapter(BaseCrawler):
    """Search and normalize jobs from the Adzuna job aggregator."""

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_key: Optional[str] = None,
        country: str = "in",
        api_base: str = ADZUNA_API,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.app_id = app_id or os.getenv("ADZUNA_APP_ID", "")
        self.app_key = app_key or os.getenv("ADZUNA_APP_KEY", "")
        self.country = country
        self.api_base = api_base
        self._client = client

    async def __aenter__(self) -> "AdzunaAdapter":
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def discover_jobs(self) -> list[CrawledJob]:
        """Default search for 'software engineer'."""
        return await self.search_by_query("software engineer")

    async def search_by_query(
        self, query: str, results_per_page: int = 50, country: Optional[str] = None
    ) -> list[CrawledJob]:
        """Search Adzuna by keyword query with retry and exponential backoff.

        Retries on transient 503 / connection failures up to
        ``ADZUNA_RETRY_MAX_ATTEMPTS`` times.  Delays between retries follow
        an exponential backoff: base * 2^(attempt-1).  After final failure,
        logs the error clearly and returns an empty list so the ingestion
        pipeline can continue with other sources/queries.
        """
        if not self.app_id or not self.app_key:
            print("Adzuna credentials not configured, skipping")
            return []

        country_code = country or self.country
        url = (
            f"{self.api_base.format(country=country_code)}"
            f"?app_id={self.app_id}&app_key={self.app_key}"
            f"&what={query}&results_per_page={results_per_page}"
            f"&content-type=application/json"
        )

        client = self._client or httpx.AsyncClient()
        owned = self._client is None
        try:
            last_exc: Exception | None = None
            for attempt in range(1, ADZUNA_RETRY_MAX_ATTEMPTS + 1):
                try:
                    response = await client.get(url)
                except httpx.HTTPError as exc:
                    last_exc = exc
                    if attempt < ADZUNA_RETRY_MAX_ATTEMPTS:
                        delay = ADZUNA_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning(
                            "Adzuna connection error for query=%r country=%s "
                            "(attempt %d/%d): %s. Retrying in %.1fs...",
                            query, country_code, attempt,
                            ADZUNA_RETRY_MAX_ATTEMPTS, exc, delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error(
                        "Adzuna connection failed for query=%r country=%s "
                        "after %d attempts: %s",
                        query, country_code, ADZUNA_RETRY_MAX_ATTEMPTS, exc,
                    )
                    return []

                if response.status_code == 200:
                    try:
                        data = response.json()
                    except ValueError:
                        logger.error(
                            "Adzuna returned invalid JSON for query=%r country=%s",
                            query, country_code,
                        )
                        return []

                    results = data.get("results", [])
                    if not isinstance(results, list):
                        return []

                    jobs = [
                        self._parse_job(raw)
                        for raw in results
                        if isinstance(raw, dict)
                    ]
                    return jobs

                # Non-200 response.
                if response.status_code == 503 and attempt < ADZUNA_RETRY_MAX_ATTEMPTS:
                    delay = ADZUNA_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "Adzuna returned 503 for query=%r country=%s "
                        "(attempt %d/%d). Retrying in %.1fs...",
                        query, country_code, attempt,
                        ADZUNA_RETRY_MAX_ATTEMPTS, delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                # Other non-200 (or final 503).
                logger.error(
                    "Adzuna API returned %d for query=%r country=%s",
                    response.status_code, query, country_code,
                )
                return []

            # Exhausted retries.
            logger.error(
                "Adzuna query failed after %d attempts: query=%r country=%s",
                ADZUNA_RETRY_MAX_ATTEMPTS, query, country_code,
            )
            return []
        finally:
            if owned and client is not None:
                await client.aclose()

    def _parse_job(self, raw: dict[str, Any]) -> CrawledJob:
        company = raw.get("company", {})
        if isinstance(company, dict):
            company_name = company.get("display_name", "")
        else:
            company_name = str(company or "")

        location = raw.get("location", {})
        if isinstance(location, dict):
            location_name = location.get("display_name", "")
        else:
            location_name = str(location or "")

        description = str(raw.get("description") or "")

        # Build salary string
        salary_min = raw.get("salary_min")
        salary_max = raw.get("salary_max")
        salary_currency = raw.get("salary_currency", "USD")
        salary = None
        if salary_min is not None and salary_max is not None:
            salary = f"{salary_min} - {salary_max} {salary_currency}"

        return CrawledJob(
            title=str(raw.get("title") or ""),
            company=company_name,
            description=description,
            location=location_name,
            employment_type=_coalesce(raw.get("contract_type")),
            apply_url=_coalesce(raw.get("redirect_url")),
            remote=_is_remote(location_name),
            external_job_id=str(raw.get("id") or ""),
            source_platform="adzuna",
            skills=_extract_known_skills(description),
            requirements=_extract_list(description, "requirements"),
            responsibilities=_extract_list(description, "responsibilities"),
            salary=salary,
            posted_date=_coalesce(raw.get("created")),
            raw=raw,
        )
