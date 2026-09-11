"""Bounded Adzuna city-query yield probe (task §5, §7, §16).

Measures, per query (10 results, 1 page, country=in):
    raw / india / foreign / unknown / target_role / india_target_role
    incremental_unique_india (canonical URL not in the role-query union)

This decides whether city-suffixed queries add genuinely NEW Indian jobs or
just duplicate the role+India baseline — the dedup guard for §7.

Usage:
    PYTHONPATH=. python scripts/probe_adzuna_city_yield.py
"""

from __future__ import annotations

import asyncio
import json

try:
    from dotenv import load_dotenv

    load_dotenv(".env")
except Exception:  # pragma: no cover
    pass

from app.crawlers.aggregators.adzuna import AdzunaAdapter
from app.services.jobs.india_geography import classify_india_relevance
from app.services.jobs.job_service import JobService
from app.services.jobs.ingestion_validation import TARGET_ROLE_KEYWORDS

ROLE_QUERIES = [
    "data analyst India",
    "data engineer India",
    "machine learning India",
    "software engineer India",
    "backend engineer India",
    "SAP ABAP India",
    "financial analyst India",
    "business analyst India",
]

CITY_QUERIES = [
    "data analyst Bengaluru",
    "data analyst Hyderabad",
    "data analyst Pune",
    "data analyst Chennai",
    "data analyst Mumbai",
    "data analyst Delhi",
    "software engineer Bengaluru",
    "software engineer Hyderabad",
    "software engineer Pune",
    "software engineer Chennai",
    "data engineer Bengaluru",
    "machine learning Bengaluru",
    "data analyst Gurugram",
    "data analyst Noida",
]


def _bucket(title: str):
    lowered = (title or "").lower()
    for bucket, kws in TARGET_ROLE_KEYWORDS.items():
        if any(k in lowered for k in kws):
            return bucket
    return None


async def main() -> None:
    service = JobService()
    async with AdzunaAdapter() as adapter:
        role_jobs = {}
        for q in ROLE_QUERIES:
            role_jobs[q] = await adapter.search_by_query(q, country="in", results_per_page=10)
        city_jobs = {}
        for q in CITY_QUERIES:
            city_jobs[q] = await adapter.search_by_query(q, country="in", results_per_page=10)

    # Build per-query stats with canonicalized URLs.
    from app.crawlers.source_quality import canonicalize_url

    role_union: set[str] = set()
    per_query: dict[str, dict] = {}
    for q, crawled in {**role_jobs, **city_jobs}.items():
        stats = {"raw": 0, "india": 0, "foreign": 0, "unknown": 0, "target_role": 0, "india_target_role": 0, "unique_canonical_india": 0}
        india_canonicals: set[str] = set()
        for cj in crawled:
            stats["raw"] += 1
            job = service.normalize_and_classify(cj)
            label = classify_india_relevance(job.location, job.remote)
            stats[label.lower()] += 1
            bucket = _bucket(job.title)
            if bucket:
                stats["target_role"] += 1
                if label == "INDIA":
                    stats["india_target_role"] += 1
            if label == "INDIA":
                url = canonicalize_url(job.apply_url or job.url) or ""
                if url:
                    india_canonicals.add(url)
        stats["unique_canonical_india"] = len(india_canonicals)
        per_query[q] = stats
        if q in ROLE_QUERIES:
            role_union |= india_canonicals

    # Incremental India = India canonicals NOT in the role-query union.
    for q in CITY_QUERIES:
        crawled = city_jobs[q]
        india_canonicals: set[str] = set()
        for cj in crawled:
            job = service.normalize_and_classify(cj)
            if classify_india_relevance(job.location, job.remote) == "INDIA":
                url = canonicalize_url(job.apply_url or job.url) or ""
                if url:
                    india_canonicals.add(url)
        per_query[q]["incremental_unique_india"] = len(india_canonicals - role_union)

    report = {"role_union_unique_india": len(role_union), "per_query": per_query}
    with open("_adzuna_city_yield.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())