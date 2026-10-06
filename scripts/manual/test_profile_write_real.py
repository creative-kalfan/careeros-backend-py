"""REAL authenticated end-to-end verification of the profile write path.

Authenticates against live Supabase with the test user, then drives the real
FastAPI application (no mocks) through httpx ASGITransport:

    GET  /api/profile/me          (authenticated)
    PATCH /api/profile/me         desired_role = "Software Engineer"
    GET  /api/profile/me          read-back (must equal "Software Engineer")
    GET  /api/jobs/personalized   personalized feed using the saved profile

This is the first real end-to-end check of:
    Authentication -> Profile write -> Profile read -> Personalization -> Jobs API
"""

from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv
from supabase import create_client

backend_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_root)
load_dotenv(os.path.join(backend_root, ".env"))

from app.main import app  # noqa: E402

BASE_URL = "http://testserver"


def login() -> tuple[str, str]:
    """Log in with the test user and return (jwt, user_id)."""
    email = os.environ.get("TEST_USER_EMAIL")
    password = os.environ.get("TEST_USER_PASSWORD")
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    anon = os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    for var, name in ((email, "TEST_USER_EMAIL"), (password, "TEST_USER_PASSWORD"), (url, "NEXT_PUBLIC_SUPABASE_URL"), (anon, "NEXT_PUBLIC_SUPABASE_ANON_KEY")):
        if not var:
            raise SystemExit(f"Missing env var: {name}")

    supabase = create_client(url, anon)
    response = supabase.auth.sign_in_with_password({"email": email, "password": password})
    if not response.session:
        raise SystemExit("Login failed: no session")
    print(f"Login OK, user.id={response.user.id}")
    return response.session.access_token, response.user.id


def call(client: httpx.AsyncClient, method: str, path: str, jwt: str, **kwargs):
    headers = {"Authorization": f"Bearer {jwt}"}
    return client.request(method, f"{BASE_URL}{path}", headers=headers, **kwargs)


async def main() -> None:
    jwt, user_id = login()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        # 1) Unauthenticated -> 401
        r = await client.get(f"{BASE_URL}/api/profile/me")
        print(f"[1] GET /api/profile/me (no auth) -> {r.status_code}")
        assert r.status_code == 401, r.text

        # 2) Initial authenticated GET
        r = await call(client, "GET", "/api/profile/me", jwt)
        print(f"[2] GET /api/profile/me (auth) -> {r.status_code}")
        assert r.status_code == 200, r.text
        initial = r.json()["data"]
        print(f"    desired_role={initial.get('desired_role')!r}")

        # 3) PATCH desired_role only
        r = await call(
            client,
            "PATCH",
            "/api/profile/me",
            jwt,
            json={"desired_role": "Software Engineer"},
        )
        print(f"[3] PATCH /api/profile/me desired_role -> {r.status_code}")
        assert r.status_code == 200, r.text
        patched = r.json()["data"]
        print(f"    desired_role={patched.get('desired_role')!r}")
        assert patched.get("desired_role") == "Software Engineer"

        # 4) Read-back
        r = await call(client, "GET", "/api/profile/me", jwt)
        assert r.status_code == 200, r.text
        readback = r.json()["data"]
        print(f"[4] GET /api/profile/me read-back desired_role={readback.get('desired_role')!r}")
        assert readback.get("desired_role") == "Software Engineer"

        # 5) Partial update preserves other fields
        r = await call(client, "PATCH", "/api/profile/me", jwt, json={"skills": ["python", "sql"]})
        assert r.status_code == 200, r.text
        after_skills = r.json()["data"]
        assert after_skills.get("desired_role") == "Software Engineer", after_skills
        assert after_skills.get("skills") == ["python", "sql"], after_skills
        print("[5] PATCH skills preserved desired_role and set skills")

        # 6) Personalized jobs with the real profile
        r = await call(client, "GET", "/api/jobs/personalized?page=1&page_size=10", jwt)
        print(f"[6] GET /api/jobs/personalized -> {r.status_code}")
        assert r.status_code == 200, r.text
        jobs = r.json().get("data", [])
        meta = r.json().get("meta", {})
        print(f"    jobs returned={len(jobs)} total={meta.get('total')}")
        for job in jobs[:5]:
            print(f"    - {job.get('title')} [{job.get('role_category')}] match={job.get('match')}")

        # 7) Error: user cannot smuggle another user id
        r = await call(
            client,
            "PATCH",
            "/api/profile/me",
            jwt,
            json={"desired_role": "Data Scientist", "id": "00000000-0000-0000-0000-000000000000"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["id"] == user_id, r.text
        print("[7] PATCH with foreign id ignored (id stays the authenticated user)")

        # Restore original desired_role state to not leave the DB dirty
        r = await call(
            client,
            "PATCH",
            "/api/profile/me",
            jwt,
            json={"desired_role": initial.get("desired_role")},
        )
        assert r.status_code == 200, r.text
        print(f"[8] restored desired_role -> {r.json()['data'].get('desired_role')!r}")

    print("\nALL REAL END-TO-END CHECKS PASSED")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
