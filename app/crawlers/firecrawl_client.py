"""Firecrawl API client (backend-only).

Thin, typed HTTP wrapper around the Firecrawl v1 REST API. Nothing else in
CareerOS talks to Firecrawl directly — domain code uses
:class:`app.crawlers.adapters.firecrawl.FirecrawlAdapter`.

Security: the API key is read from environment configuration only, is never
logged, never returned in error messages, and never sent anywhere except the
Firecrawl Authorization header.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class FirecrawlError(Exception):
    """Base error for Firecrawl API failures (safe to surface/log)."""


class FirecrawlConfigurationError(FirecrawlError):
    """Firecrawl was invoked without a configured API key."""


class FirecrawlAuthError(FirecrawlError):
    """Authentication failed (401/403) — the API key is invalid/revoked."""


class FirecrawlRateLimitError(FirecrawlError):
    """Rate limited (429) after exhausting retries."""


class FirecrawlServerError(FirecrawlError):
    """Firecrawl returned 5xx after exhausting retries."""


class FirecrawlJobTimeout(FirecrawlError):
    """An asynchronous crawl job did not complete within the poll budget."""


_STATUS_TO_ERROR = {
    401: FirecrawlAuthError,
    403: FirecrawlAuthError,
}


class FirecrawlClient:
    """Authenticated HTTP client for the Firecrawl v1 API.

    Features: timeout, exponential backoff with jitter on 429/5xx/network
    errors, typed errors, and secret-safe logging (only status codes and
    URLs are ever logged — never headers or keys).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.firecrawl_api_key
        self._api_url = (api_url or settings.firecrawl_api_url).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.firecrawl_timeout_seconds
        self._max_retries = max_retries if max_retries is not None else settings.firecrawl_max_retries
        self._client = client

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "FirecrawlClient":
        self._ensure_client()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    def _require_key(self) -> str:
        if not self._api_key:
            raise FirecrawlConfigurationError(
                "FIRECRAWL_API_KEY is not configured; Firecrawl crawling is unavailable."
            )
        return self._api_key

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with jitter: 1.0s, 2.0s, 4.0s ... (±20%)."""
        base = 1.0 * (2 ** attempt)
        return base * (0.8 + 0.4 * random.random())

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON with retry/backoff; raises typed errors on failure."""
        key = self._require_key()
        client = self._ensure_client()
        url = f"{self._api_url}{path}"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

        last_error: Optional[Exception] = None
        last_status = 0
        for attempt in range(self._max_retries + 1):
            try:
                response = await client.post(url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                logger.warning("Firecrawl network error (attempt %d): %s", attempt + 1, exc.__class__.__name__)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._backoff_delay(attempt))
                continue

            status = response.status_code
            if status < 400:
                try:
                    return response.json()
                except ValueError as exc:
                    raise FirecrawlError(f"Firecrawl returned malformed JSON from {path}") from exc

            error_cls = _STATUS_TO_ERROR.get(status)
            if error_cls:
                raise error_cls(f"Firecrawl request rejected with HTTP {status}")

            if status == 429 or status >= 500:
                last_error = None
                last_status = status
                logger.warning("Firecrawl HTTP %d (attempt %d)", status, attempt + 1)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._backoff_delay(attempt))
                continue

            # Other 4xx: deterministic client error — do not retry.
            raise FirecrawlError(f"Firecrawl request failed with HTTP {status}")

        if last_status == 429:
            raise FirecrawlRateLimitError(
                f"Firecrawl rate limited (429) after {self._max_retries + 1} attempts"
            )
        if isinstance(last_error, (httpx.TimeoutException, httpx.TransportError)):
            raise FirecrawlError(
                f"Firecrawl request failed after {self._max_retries + 1} attempts: {last_error.__class__.__name__}"
            ) from last_error
        raise FirecrawlServerError(f"Firecrawl request failed after {self._max_retries + 1} attempts")

    async def _get(self, path: str) -> dict[str, Any]:
        """GET JSON with the same error typing as _post."""
        key = self._require_key()
        client = self._ensure_client()
        url = f"{self._api_url}{path}"
        headers = {"Authorization": f"Bearer {key}"}
        response = await client.get(url, headers=headers)
        if response.status_code < 400:
            try:
                return response.json()
            except ValueError as exc:
                raise FirecrawlError(f"Firecrawl returned malformed JSON from {path}") from exc
        error_cls = _STATUS_TO_ERROR.get(response.status_code)
        if error_cls:
            raise error_cls(f"Firecrawl request rejected with HTTP {response.status_code}")
        raise FirecrawlError(f"Firecrawl request failed with HTTP {response.status_code}")

    # ------------------------------------------------------------------
    # Public API (Firecrawl v1 endpoints)
    # ------------------------------------------------------------------

    async def map(self, url: str, limit: int = 100) -> list[str]:
        """Discover URLs under a site (/map endpoint)."""
        data = await self._post("/map", {"url": url, "limit": limit})
        links = data.get("links") or []
        return [link for link in links if isinstance(link, str)]

    async def scrape(self, url: str, formats: Optional[list[str]] = None) -> dict[str, Any]:
        """Scrape a single page (/scrape endpoint).

        Returns the raw response; the page document lives under ``data``.
        """
        payload: dict[str, Any] = {"url": url, "formats": formats or ["markdown", "html"]}
        return await self._post("/scrape", payload)

    async def crawl(
        self,
        url: str,
        limit: int = 10,
        poll_attempts: int = 20,
        poll_interval: float = 2.0,
    ) -> list[dict[str, Any]]:
        """Start an asynchronous crawl job and poll it to completion.

        Bounded by ``poll_attempts`` so a stuck job can never hang a worker.
        """
        started = await self._post("/crawl", {"url": url, "limit": limit})
        job_id = (started or {}).get("id")
        if not job_id:
            # Some responses return the completed payload synchronously.
            data = (started or {}).get("data")
            if isinstance(data, list):
                return data
            raise FirecrawlError("Firecrawl crawl did not return a job id")

        for _ in range(poll_attempts):
            await asyncio.sleep(poll_interval)
            status = await self._get(f"/crawl/{job_id}")
            job_status = status.get("status")
            if job_status == "completed":
                return status.get("data") or []
            if job_status == "failed":
                raise FirecrawlError("Firecrawl crawl job failed")
        raise FirecrawlJobTimeout(f"Firecrawl crawl job did not complete in time")

