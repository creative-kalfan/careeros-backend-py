"""Bounded live validation of the India coverage changes (task §18, §22).

Runs ONE bounded canonical Adzuna ingest (scheduled-path behavior: primary
query + new rotation batch) against the live DB and measures before/after:

    active total / India / India% / adzuna active / incremental India
    India city diversity / KPI family

Adzuna calls: 3 primary + 3 rotated = 6 (50 results/page), well within the
free-tier budget. No deactivation runs here (that lives in the ARQ worker).
"""

from __future__ import annotations

import asyncio
import json

try:
    from dotenv import load_dotenv

    load_dotenv(".env")
except Exception:  # pragma: no cover
    pass

from app.crawlers.source_quality import canonicalize_url
from app.db.supabase import get_service_client
from app.services.jobs.ingestion_validation import india_kpis
from app.services.jobs.india_geography import classify_india_relevance, INDIAN_CITY_TOKENS
from app.services.jobs.job_ingestion_service import JobIngestionService


def _fetch_active(client):
    rows = []
    offset = 0
    while True:
        res = client.table("jobs").select("id, title, company, location, url, canonical_url, source_platform, external_job_id, posted_at").eq("is_active", True).range(offset, offset + 999).execute()
        chunk = res.data or []
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000
    return rows


def _city_of(location: str) -> str:
    lowered = (location or "").lower()
    for city in INDIAN_CITY_TOKENS:
        if city in lowered:
            return city.title() if city != "new delhi" else "Delhi NCR"
    return "India (unspecified)"


def _measure(rows):
    from collections import Counter

    geo = Counter(classify_india_relevance(r.get("location"), r.get("remote")) for r in rows)
    provider_geo = Counter()
    cities = Counter()
    for r in rows:
        label = classify_india_relevance(r.get("location"), r.get("remote"))
        provider = r.get("source_platform") or "none"
        provider_geo[(provider, label)] += 1
        if label == "INDIA":
            cities[_city_of(r.get("location") or "")] += 1
    return {
        "total_active": len(rows),
        "geo": dict(geo),
        "india_pct": round(100.0 * geo["INDIA"] / len(rows), 1) if rows else 0.0,
        "adzuna_active": provider_geo.get(("adzuna", "INDIA"), 0) + provider_geo.get(("adzuna", "FOREIGN"), 0) + provider_geo.get(("adzuna", "AMBIGUOUS"), 0) + provider_geo.get(("adzuna", "UNKNOWN"), 0),
        "india_by_provider": {p: c for (p, l), c in provider_geo.items() if l == "INDIA"},
        "india_cities": dict(cities.most_common()),
    }


async def main() -> None:
    client = get_service_client()
    before_rows = _fetch_active(client)
    before = _measure(before_rows)

    # Existing adzuna canonical inventory (for incremental KPI).
    adzuna_rows = client.table("jobs").select("canonical_url, url").eq("source_platform", "adzuna").limit(2000).execute().data or []
    existing_adzuna = {canonicalize_url(r.get("canonical_url") or r.get("url") or "") for r in adzuna_rows if r.get("canonical_url") or r.get("url")}
    existing_adzuna.discard("")

    result = await JobIngestionService().ingest_adzuna_jobs("software engineer")

    after_rows = _fetch_active(client)
    after = _measure(after_rows)

    # Incremental India KPIs over the fresh adzuna canonical set.
    fresh_adzuna = client.table("jobs").select("canonical_url, url, title, location, external_job_id, posted_at").eq("source_platform", "adzuna").eq("is_active", True).limit(1000).execute().data or []
    from app.models.job import NormalizedJob

    fresh_jobs = []
    for r in fresh_adzuna:
        try:
            r2 = dict(r)
            r2.setdefault("source_platform", "adzuna")
            r2.setdefault("title", "")
            r2["posted_date"] = r2.get("posted_at")
            fresh_jobs.append(NormalizedJob.model_validate(r2))
        except Exception:
            continue
    kpis = india_kpis(fresh_jobs, existing_adzuna, provider_calls=6)

    report = {
        "before": before,
        "after": after,
        "ingest_result": result,
        "kpis": kpis,
        "delta": {
            "total_active": after["total_active"] - before["total_active"],
            "india": after["geo"].get("INDIA", 0) - before["geo"].get("INDIA", 0),
            "adzuna_active": after["adzuna_active"] - before["adzuna_active"],
        },
    }
    with open("_live_validation.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())