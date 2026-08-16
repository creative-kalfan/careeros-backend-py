"""Verify final DB state after re-ingestion: India jobs + 30-day cutoff."""
import os
from datetime import datetime, timezone, timedelta


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

client = get_service_client()

total_active = (client.table("jobs").select("id", count="exact").eq("is_active", True).execute().count) or 0
print(f"Total active jobs: {total_active}")

adzuna_active = (client.table("jobs").select("id", count="exact").eq("source_platform", "adzuna").eq("is_active", True).execute().count) or 0
print(f"Adzuna active jobs: {adzuna_active}")

print("\nBangalore Adzuna jobs (sample):")
r = (
    client.table("jobs")
    .select("title, company, location, posted_at, is_active")
    .eq("source_platform", "adzuna")
    .ilike("location", "%Bangalore%")
    .limit(5)
    .execute()
)
for x in r.data or []:
    print(f"  - {x.get('title')} | {x.get('company')} | {x.get('location')} | posted={x.get('posted_at')} | active={x.get('is_active')}")

print("\nPune Adzuna jobs (sample):")
r2 = (
    client.table("jobs")
    .select("title, company, location, posted_at, is_active")
    .eq("source_platform", "adzuna")
    .ilike("location", "%Pune%")
    .limit(5)
    .execute()
)
for x in r2.data or []:
    print(f"  - {x.get('title')} | {x.get('company')} | {x.get('location')} | posted={x.get('posted_at')} | active={x.get('is_active')}")

print("\nStale check (active jobs with posted_at > 30 days old):")
cutoff = datetime.now(timezone.utc) - timedelta(days=30)
r3 = (
    client.table("jobs")
    .select("title, company, posted_at, is_active")
    .eq("is_active", True)
    .limit(1000)
    .execute()
)
stale_active = 0
for x in r3.data or []:
    posted = x.get("posted_at")
    if posted:
        try:
            dt = datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                stale_active += 1
        except Exception:
            pass
print(f"  Active jobs older than 30 days (should be 0): {stale_active}")
