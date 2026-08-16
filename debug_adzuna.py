"""Debug Adzuna adapter and ingestion."""
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

from app.crawlers.aggregators.adzuna import AdzunaAdapter
from app.db.supabase import get_service_client
from app.services.jobs.job_ingestion_service import JobIngestionService


async def main() -> None:
    # 1. Test adapter directly
    print("=== 1. Adzuna adapter direct test ===")
    adapter = AdzunaAdapter()
    india_jobs = await adapter.search_by_query("software engineer", country="in", results_per_page=10)
    print(f"India search returned {len(india_jobs)} jobs")
    for j in india_jobs[:5]:
        print(f"  - {j.title} | {j.company} | {j.location} | id={j.external_job_id}")

    # 2. Test ingestion service
    print("\n=== 2. Ingestion service test ===")
    service = JobIngestionService()
    result = await service.ingest_adzuna_jobs()
    print(f"Ingestion result: {result}")

    # 3. Check DB after
    print("\n=== 3. DB check after ingestion ===")
    client = get_service_client()
    r = client.table("jobs").select("id", count="exact").eq("source_platform", "adzuna").execute()
    print(f"Adzuna total rows: {r.count}")

    r2 = client.table("jobs").select("title,company,location,is_active,posted_at").eq("source_platform", "adzuna").ilike("location", "%Bangalore%").limit(5).execute()
    print(f"Bangalore jobs: {len(r2.data or [])}")
    for x in r2.data or []:
        print(f"  - {x.get('title')} | {x.get('company')} | {x.get('location')} | active={x.get('is_active')} | posted={x.get('posted_at')}")

    r3 = client.table("jobs").select("title,company,location,is_active,posted_at").eq("source_platform", "adzuna").ilike("location", "%Pune%").limit(5).execute()
    print(f"Pune jobs: {len(r3.data or [])}")
    for x in r3.data or []:
        print(f"  - {x.get('title')} | {x.get('company')} | {x.get('location')} | active={x.get('is_active')} | posted={x.get('posted_at')}")


if __name__ == "__main__":
    asyncio.run(main())