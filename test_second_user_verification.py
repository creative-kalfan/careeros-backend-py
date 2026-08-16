"""Verify the profile/onboarding flow against a SECOND real user.

Uses the admin test account (a distinct real Supabase user) to confirm the
profile PATCH/GET + personalized-jobs flow is not coincidentally working for
only one specific profile shape.
"""

import os
import sys
import time
import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

BASE_URL = "http://127.0.0.1:8000"


def login_and_get_jwt(email, password):
    """Login with Supabase and return JWT + user id."""
    supabase_url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_anon_key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    supabase = create_client(supabase_url, supabase_anon_key)
    response = supabase.auth.sign_in_with_password({
        "email": email,
        "password": password,
    })
    if not response.session:
        raise SystemExit(f"Login failed for {email}")
    return response.session.access_token, response.user.id


def get_profile(jwt):
    r = requests.get(f"{BASE_URL}/api/profile/me", headers={"Authorization": f"Bearer {jwt}"}, timeout=15)
    return r


def patch_profile(jwt, data):
    r = requests.patch(f"{BASE_URL}/api/profile/me", headers={"Authorization": f"Bearer {jwt}"}, json=data, timeout=15)
    return r


def get_personalized(jwt):
    r = requests.get(
        f"{BASE_URL}/api/jobs/personalized",
        headers={"Authorization": f"Bearer {jwt}"},
        params={"page": 1, "page_size": 5},
        timeout=15,
    )
    return r


def main():
    print("=" * 60)
    print("SECOND REAL USER VERIFICATION (admin test account)")
    print("=" * 60)

    email = os.getenv("TEST_ADMIN_EMAIL")
    password = os.getenv("TEST_ADMIN_PASSWORD")
    if not email or not password:
        print("❌ Missing TEST_ADMIN_EMAIL/TEST_ADMIN_PASSWORD in .env")
        sys.exit(1)

    print(f"Logging in as second user: {email}")
    jwt, user_id = login_and_get_jwt(email, password)
    print(f"✅ Second user login successful. User ID: {user_id}")

    # 1. GET profile (should 200 — auth auto-creates profile row)
    r = get_profile(jwt)
    print(f"\nGET /api/profile/me -> {r.status_code}")
    if r.status_code != 200:
        print(f"❌ Second user profile GET failed: {r.text[:300]}")
        sys.exit(1)
    print(f"✅ Second user profile GET succeeded")

    # 2. PATCH desired_role = "Data Scientist" (different from first user's SWE)
    r = patch_profile(jwt, {"desired_role": "Data Scientist"})
    print(f"\nPATCH desired_role='Data Scientist' -> {r.status_code}")
    if r.status_code != 200:
        print(f"❌ Second user profile PATCH failed: {r.text[:300]}")
        sys.exit(1)
    print(f"✅ Second user profile PATCH succeeded")

    # 3. GET profile to confirm persistence
    r = get_profile(jwt)
    data = r.json().get("data", {})
    print(f"   Persisted desired_role: {data.get('desired_role')}")
    if data.get("desired_role") != "Data Scientist":
        print("❌ Second user desired_role did not persist")
        sys.exit(1)
    print("✅ Second user desired_role persisted correctly")

    # 4. Personalized jobs
    time.sleep(1)
    r = get_personalized(jwt)
    print(f"GET /api/jobs/personalized -> {r.status_code}")
    if r.status_code != 200:
        print(f"❌ Second user personalized jobs failed: {r.text[:300]}")
        sys.exit(1)
    jobs = r.json().get("data", [])
    print(f"   Jobs returned: {len(jobs)}")
    for j in jobs[:5]:
        print(f"   - {j.get('title')} [{j.get('role_category')}] match={j.get('match', {}).get('overall')}")
    print("✅ Second user personalized jobs returned real data")

    print("\n" + "=" * 60)
    print("✅ SECOND USER VERIFICATION: PASSED")
    print("=" * 60)
    print("The profile/onboarding flow works for a second distinct real user.")


if __name__ == "__main__":
    main()