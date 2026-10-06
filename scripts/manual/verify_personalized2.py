"""Verify /jobs/personalized with the real (onboarded) user."""
import os

os.environ.setdefault(
    "NEXT_PUBLIC_SUPABASE_URL",
    "https://wjayvttrifpqtjloeunc.supabase.co",
)
os.environ.setdefault(
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndqYXl2dHRyaWZwcXRqbG9ldW5jIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM5MDYwMTQsImV4cCI6MjA5OTQ4MjAxNH0.sK3khuaKTwA6WfJMVQfmMJzHYvEqTXxGjCOuEdxRFMk",
)

import httpx
from supabase import create_client


def main() -> None:
    sb = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"],
    )
    res = sb.auth.sign_in_with_password(
        {"email": "kalfanpathan@gmail.com", "password": "1qaz@Mlp0"}
    )
    token = res.session.access_token
    headers = {"Authorization": f"Bearer {token}"}

    r = httpx.get("http://localhost:8000/api/profile/me", headers=headers)
    prof = (r.json().get("data") or r.json()) if r.status_code == 200 else None
    if prof:
        print("Profile: skills=", prof.get("skills"), "desired=", prof.get("desired_role"), "loc=", prof.get("location"))

    r = httpx.get(
        "http://localhost:8000/jobs/personalized?page=1&pageSize=10&includeAts=true",
        headers=headers,
    )
    print("Status:", r.status_code)
    data = r.json()
    jobs = data.get("data", [])
    print("Meta:", data.get("meta"))
    print("--- First 10 jobs ---")
    for j in jobs:
        company = j.get("company", "?") or "?"
        overall = j.get("match", {}).get("overall") if j.get("match") else "?"
        title = (j.get("title", "") or "")[:40]
        loc = (j.get("location", "") or "")[:20]
        print(f"{company:14} | score={str(overall):4} | {title:42} | {loc}")


if __name__ == "__main__":
    main()