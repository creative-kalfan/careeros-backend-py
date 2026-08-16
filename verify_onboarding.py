"""Verify GET /api/profile/me returns onboarding_completed for the test user."""
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

import httpx
from supabase import create_client

EMAIL = "kalfanpathan@gmail.com"
PASSWORD = "1qaz@Mlp0"

SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")


def main() -> None:
    # 1. Login via Supabase to get a JWT
    sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    res = sb.auth.sign_in_with_password({"email": EMAIL, "password": PASSWORD})
    access_token = res.session.access_token
    print("Logged in. JWT prefix:", access_token[:20], "...")

    # 2. Call GET /api/profile/me with the JWT
    headers = {"Authorization": f"Bearer {access_token}"}
    r = httpx.get("http://localhost:8000/api/profile/me", headers=headers)
    print("Status:", r.status_code)
    data = r.json()
    print("Response:", data)
    if r.status_code == 200:
        profile = data.get("data", {})
        print("\nonboarding_completed:", profile.get("onboarding_completed"))
        print("onboarding_step:", profile.get("onboarding_step"))


if __name__ == "__main__":
    main()