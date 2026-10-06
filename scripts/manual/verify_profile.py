"""Check test user profile to understand why scores are uniform."""
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
        {"email": "careeros-test-user@example.com", "password": "TestUser123!"}
    )
    token = res.session.access_token
    user_id = res.user.id
    print("User ID:", user_id)
    headers = {"Authorization": f"Bearer {token}"}

    r = httpx.get("http://localhost:8000/api/profile/me", headers=headers)
    print("Profile status:", r.status_code)
    if r.status_code == 200:
        prof = r.json().get("data") or r.json()
        print("Profile keys:", list(prof.keys()) if isinstance(prof, dict) else "n/a")
        print("Profile:", prof)


if __name__ == "__main__":
    main()