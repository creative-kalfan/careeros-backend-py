"""Verify description HTML is stripped and apply_url is present."""
import os

os.environ.setdefault(
    "NEXT_PUBLIC_SUPABASE_URL",
    "https://wjayvttrifpqtjloeunc.supabase.co",
)
os.environ.setdefault(
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndqYXl2dHRyaWZwcXRjbG9ldW5jIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM5MDYwMTQsImV4cCI6MjA5OTQ4MjAxNH0.sK3khuaKTwA6WfJMVQfmMJzHYvEqTXxGjCOuEdxRFMk",
)

import httpx
from supabase import create_client


def main() -> None:
    sb = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"],
    )
    res = sb.auth.sign_in_with_password(
        {"email": "careeros-test-user@example.com", "password": "TestUser123!"}
    )
    token = res.session.access_token
    headers = {"Authorization": f"Bearer {token}"}

    r = httpx.get(
        "http://localhost:8000/jobs/personalized?page=1&pageSize=3&includeAts=true",
        headers=headers,
    )
    print("Status:", r.status_code)
    jobs = r.json().get("data", [])
    for j in jobs:
        desc = j.get("description", "") or ""
        has_html = "<" in desc and ">" in desc
        print(f"--- {j.get('title','')[:40]} ---")
        print(f"  company: {j.get('company')}")
        print(f"  apply_url: {j.get('apply_url')}")
        print(f"  match.overall: {j.get('match', {}).get('overall')}")
        print(f"  description has HTML tags: {has_html}")
        print(f"  description preview: {desc[:120]}")


if __name__ == "__main__":
    main()