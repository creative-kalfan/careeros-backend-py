"""Full re-ingestion run across all 5 job sources.

Freshly crawls and upserts jobs from Ashby, Greenhouse, SmartRecruiters,
Lever, and Adzuna (India-first), replacing stale/synthetic rows where
possible and reporting before/after row counts per source.
"""
import asyncio
import os
from datetime import datetime, timezone


def _load_env() -> None:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_load_env()

from app.db.supabase import get_service_client
from app.services.jobs.job_ingestion_service import JobIngestionService


def count_rows(client, source: str | None = None) -> int:
    q = client.table("jobs").select("id", count="exact")
    if source:
        q = q.eq("source_platform", source)
    return (q.execute().count) or 0


async def main() -> None:
    client = get_service_client()
    service = JobIngestionService()

    sources = ["ashby", "greenhouse", "smartrecruiters", "lever", "adzuna"]
    print("=== BEFORE row counts ===")
    before = {}
    for s in sources:
        before[s] = count_rows(client, s)
        print(f"  {s}: {before[s]}")

    results = await service.ingest_all()

    print("\n=== Ingestion results per source ===")
    for s in sources:
        print(f"  {s}: {results.get(s)}")

    print("\n=== AFTER row counts ===")
    after = {}
    for s in sources:
        after[s] = count_rows(client, s)
        print(f"  {s}: {after[s]} (delta {after[s] - before[s]})")


if __name__ == "__main__":
    asyncio.run(main())