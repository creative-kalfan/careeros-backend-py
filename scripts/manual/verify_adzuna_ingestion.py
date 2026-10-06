"""Targeted Adzuna India-first ingestion + verify India jobs land in DB."""
import asyncio
import os


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


async def main() -> None:
    client = get_service_client()
    service = JobIngestionService()

    before = (
        client.table("jobs").select("id", count="exact").eq("source_platform", "adzuna").execute().count
    ) or 0
    print(f"Adzuna rows before: {before}")

    result = await service.ingest_adzuna_jobs()
    print("Ingestion result:", result)

    after = (
        client.table("jobs").select("id", count="exact").eq("source_platform", "adzuna").execute().count
    ) or 0
    print(f"Adzuna rows after: {after} (delta {after - before})")

    print("\nIndia-located Adzuna jobs now in DB (sample):")
    r = (
        client.table("jobs")
        .select("title, company, location, is_active, posted_at")
        .eq("source_platform", "adzuna")
        .ilike("location", "%Bangalore%")
        .limit(5)
        .execute()
    )
    bangalore = r.data or []
    print(f"  Bangalore: {len(bangalore)}")
    for x in bangalore:
        print(f"    - {x.get('title')} | {x.get('company')} | {x.get('location')} | active={x.get('is_active')}")

    r2 = (
        client.table("jobs")
        .select("title, company, location, is_active, posted_at")
        .eq("source_platform", "adzuna")
        .ilike("location", "%Pune%")
        .limit(5)
        .execute()
    )
    pune = r2.data or []
    print(f"  Pune: {len(pune)}")
    for x in pune:
        print(f"    - {x.get('title')} | {x.get('company')} | {x.get('location')} | active={x.get('is_active')}")


if __name__ == "__main__":
    asyncio.run(main())