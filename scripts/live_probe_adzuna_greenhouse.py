"""Bounded live probes (task §3, §5, §6, §18).

Adzuna: per-query India yield for the priority query matrix (country=in,
results_per_page=10, single page) — no DB writes.

Greenhouse: Stripe board list (single API call) location distribution to
answer "does the board expose location info & can India be identified?".

Usage:
    PYTHONPATH=. python scripts/live_probe_adzuna_greenhouse.py
"""

from __future__ import annotations

import asyncio
import json
import os

try:
    from dotenv import load_dotenv

    load_dotenv(".env")
except Exception:  # pragma: no cover
    pass

from app.crawlers.aggregators.adzuna import AdzunaAdapter
from app.services.jobs.india_geography import classify_india_relevance
from app.services.jobs.job_service import JobService
from app.services.jobs.ingestion_validation import TARGET_ROLE_KEYWORDS


def _target_role_bucket(title: str) -> str | None:
    """First target-role bucket matching the title, else None."""
    lowered = (title or "").lower()
    for bucket, keywords in TARGET_ROLE_KEYWORDS.items():
        if any(k in lowered for k in keywords):
            return bucket
    return None

ADZUNA_PRIORITY_QUERIES = [
    "data analyst India",
    "data engineer India",
    "machine learning India",
    "software engineer India",
    "backend engineer India",
    "SAP ABAP India",
    "financial analyst India",
    "business analyst India",
]

GREENHOUSE_SLUG = "stripe"


async def probe_adzuna(service: JobService) -> dict:
    results: dict[str, dict] = {}
    overall = {"raw": 0, "india": 0, "foreign": 0, "ambiguous": 0, "unknown": 0, "target_role": 0, "india_target_role": 0}
    async with AdzunaAdapter() as adapter:
        for query in ADZUNA_PRIORITY_QUERIES:
            try:
                crawled = await adapter.search_by_query(query, country="in", results_per_page=10)
            except Exception as exc:  # pragma: no cover - isolated probe
                results[query] = {"error": f"{exc.__class__.__name__}: {exc}"}
                continue
            stats = {"raw": 0, "valid": 0, "stale": 0, "invalid": 0, "india": 0, "foreign": 0, "ambiguous": 0, "unknown": 0, "target_role": 0, "india_target_role": 0}
            for crawled_job in crawled:
                stats["raw"] += 1
                overall["raw"] += 1
                job = service.normalize_and_classify(crawled_job)
                from app.services.jobs.job_service import validate_job

                status, _ = validate_job(job)
                if status == "INVALID":
                    stats["invalid"] += 1
                elif status == "STALE":
                    stats["stale"] += 1
                else:
                    stats["valid"] += 1
                label = classify_india_relevance(job.location, job.remote)
                stats[label.lower()] += 1
                overall[label.lower()] += 1
                bucket = _target_role_bucket(job.title)
                if bucket:
                    stats["target_role"] += 1
                    overall["target_role"] += 1
                    if label == "INDIA":
                        stats["india_target_role"] += 1
                        overall["india_target_role"] += 1
            results[query] = stats
    return {"per_query": results, "overall": overall}


async def probe_greenhouse() -> dict:
    from app.crawlers.adapters.greenhouse import GreenhouseAdapter

    async with GreenhouseAdapter(GREENHOUSE_SLUG) as adapter:
        jobs = await adapter.discover_jobs()
    from collections import Counter

    location_counter: Counter[str] = Counter()
    india_detectable = 0
    for job in jobs:
        location_counter[str(job.location or "")] += 1
        if classify_india_relevance(job.location, job.remote) == "INDIA":
            india_detectable += 1
    return {
        "board": GREENHOUSE_SLUG,
        "total_listed": len(jobs),
        "india_detectable": india_detectable,
        "top_locations": location_counter.most_common(30),
    }


async def main() -> None:
    service = JobService()
    adzuna = await probe_adzuna(service)
    greenhouse = await probe_greenhouse()
    report = {"adzuna": adzuna, "greenhouse": greenhouse}
    with open("_live_probe.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())