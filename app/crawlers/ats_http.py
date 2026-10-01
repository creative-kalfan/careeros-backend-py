"""Shared bounded HTTP behavior for public ATS adapters."""

from __future__ import annotations

import asyncio
import random

import httpx

from app.config import get_settings


def timeout_config() -> httpx.Timeout:
    settings = get_settings()
    return httpx.Timeout(settings.ats_read_timeout_seconds, connect=settings.ats_connect_timeout_seconds)


def request_semaphore() -> asyncio.Semaphore:
    return asyncio.Semaphore(max(1, get_settings().ats_fetch_concurrency))


async def get_json_response(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """Retry bounded 429/5xx responses with jitter; propagate transport failures."""
    for attempt in range(3):
        response = await client.get(url, **kwargs)
        if response.status_code != 429 and response.status_code < 500:
            return response
        if attempt == 2:
            response.raise_for_status()
        await asyncio.sleep(0.2 * (2**attempt) + random.random() * 0.2)
    raise RuntimeError("unreachable")
