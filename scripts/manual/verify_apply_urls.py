"""Verify real apply_url values exist per source in the jobs table."""
import asyncio
import sys

from app.db.supabase import get_service_client


def main() -> None:
    client = get_service_client()
    sources = ["ashby", "greenhouse", "smartrecruiters", "lever", "adzuna"]
    print("=== Real apply_url per source (most recent active job) ===\n")
    for source in sources:
        result = (
            client.table("jobs")
            .select("id, title, company, url, source_platform, posted_at, is_active")
            .eq("source_platform", source)
            .eq("is_active", True)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            print(f"[{source}] NO ACTIVE JOBS FOUND")
            continue
        row = rows[0]
        print(f"[{source}]")
        print(f"  id:        {row.get('id')}")
        print(f"  title:     {row.get('title')}")
        print(f"  company:   {row.get('company')}")
        print(f"  url:       {row.get('url')}")
        print(f"  posted_at: {row.get('posted_at')}")
        print()


if __name__ == "__main__":
    main()