"""Seed a rich profile for the test user so match scores genuinely vary."""
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
    headers = {"Authorization": f"Bearer {token}"}

    # Rich profile: software engineer in Bangalore with realistic skills.
    payload = {
        "skills": [
            "Python", "Javascript", "TypeScript", "React", "Node.js",
            "SQL", "PostgreSQL", "AWS", "Docker", "Kubernetes",
            "Machine Learning", "Data Analysis",
        ],
        "desired_role": "Software Engineer",
        "location": "Bangalore, India",
        "preferred_locations": ["Bangalore", "Pune", "Bengaluru"],
        "remote_preference": "any",
        "experience": "Mid-Senior",
        "onboarding_completed": True,
        "onboarding_step": 3,
    }

    r = httpx.patch("http://localhost:8000/api/profile/me", json=payload, headers=headers)
    print("Update profile status:", r.status_code)
    print(r.json())


if __name__ == "__main__":
    main()