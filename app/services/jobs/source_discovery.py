"""Bounded discovery of public ATS boards from existing job URLs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any

import httpx

from app.config import get_settings
from app.db.supabase import get_service_client

logger = logging.getLogger(__name__)


def parse_ats_board(value: str | None) -> tuple[str, str] | None:
    if not value:
        return None
    parsed = urlparse(value if "://" in value else "https://" + value)
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        source = "greenhouse"
    elif host == "jobs.lever.co":
        source = "lever"
    elif host == "jobs.ashbyhq.com":
        source = "ashby"
    elif host.endswith(".smartrecruiters.com") or host == "smartrecruiters.com":
        source = "smartrecruiters"
    else:
        return None
    slug = parts[0].strip()
    return (source, slug) if slug and len(slug) <= 120 else None


def _probe_url(source: str, slug: str) -> str:
    urls = {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
        "smartrecruiters": f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
    }
    return urls[source]


async def _probe(source: str, slug: str) -> str:
    settings = get_settings()
    timeout = httpx.Timeout(settings.ats_read_timeout_seconds, connect=settings.ats_connect_timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(_probe_url(source, slug), headers={"Accept": "application/json"})
        if response.status_code == 404:
            return "dead"
        if response.status_code >= 500 or response.status_code == 429:
            return "retry"
        if response.status_code != 200:
            return "dead"
        payload = response.json()
        jobs = payload if isinstance(payload, list) else next(
            (payload.get(key) for key in ("jobs", "postings", "content") if isinstance(payload.get(key), list)),
            [],
        ) if isinstance(payload, dict) else []
        return "active" if jobs else "dead"
    except (httpx.HTTPError, ValueError):
        return "retry"


async def discover_ats_targets(ctx: dict[str, Any]) -> dict[str, int]:
    """Parse stored URLs, then probe a daily bounded candidate batch."""
    settings = get_settings()
    client = get_service_client()
    try:
        jobs = await asyncio.to_thread(
            lambda: client.table("jobs").select("url").not_.is_("url", "null").limit(5000).execute().data or []
        )
        discovered = {(s, slug) for row in jobs if (target := parse_ats_board(row.get("url"))) for s, slug in [target]}
        for source, slug in discovered:
            await asyncio.to_thread(lambda s=source, l=slug: client.table("crawl_targets").upsert({
                "source": s, "slug": l, "status": "candidate", "priority": 2,
            }, on_conflict="source,slug", ignore_duplicates=True).execute())
    except Exception as exc:
        logger.warning("ATS target discovery unavailable (%s)", type(exc).__name__)
        return {"discovered": 0, "probed": 0}

    today = datetime.now(timezone.utc).date().isoformat()
    try:
        candidates = await asyncio.to_thread(lambda: client.table("crawl_targets").select(
            "source,slug"
        ).eq("status", "candidate").or_(f"last_discovery_probe_at.is.null,last_discovery_probe_at.lt.{today}T00:00:00Z").limit(
            settings.discovery_max_probes_per_day
        ).execute().data or [])
    except Exception as exc:
        logger.warning("ATS candidate probe query unavailable (%s)", type(exc).__name__)
        return {"discovered": len(discovered), "probed": 0}
    probed = 0
    for row in candidates:
        source, slug = row["source"], row["slug"]
        outcome = await _probe(source, slug)
        probed += 1
        update = {"last_discovery_probe_at": datetime.now(timezone.utc).isoformat()}
        if outcome != "retry":
            update.update({"status": outcome, "next_run_at": datetime.now(timezone.utc).isoformat()})
        await asyncio.to_thread(lambda s=source, l=slug, values=update: client.table("crawl_targets").update(values).eq("source", s).eq("slug", l).eq("status", "candidate").execute())
    return {"discovered": len(discovered), "probed": probed}
