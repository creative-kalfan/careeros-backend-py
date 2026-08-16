"""Tests for the auth feature against a LIVE Supabase project.

These tests hit the real Supabase project referenced by the environment
variables below. They are intentionally NOT mocked: the whole point of the
RLS regression test is to confirm that the returned Supabase client actually
runs queries under the caller's RLS context (i.e. it returns the user's own
profile row) — something mocks cannot verify.

Required env vars (see .env.example):
  NEXT_PUBLIC_SUPABASE_URL
  NEXT_PUBLIC_SUPABASE_ANON_KEY
  TEST_USER_EMAIL
  TEST_USER_PASSWORD   (must have an existing corresponding auth user)
  TEST_ADMIN_EMAIL
  TEST_ADMIN_PASSWORD  (must be a user whose profiles.role == 'admin')
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from app.main import app

# Load .env so the live-Supabase test fixtures can read the credentials.
load_dotenv()


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is not set; cannot run live Supabase tests")
    return value


def _login(email: str, password: str, supabase_client) -> dict:
    """Sign in with Supabase and return the session dict."""
    res = supabase_client.auth.sign_in_with_password(
        {"email": email, "password": password}
    )
    assert res.session, f"Failed to sign in {email}"
    return res.session


@pytest.fixture(scope="module")
def supabase_url() -> str:
    return _required_env("NEXT_PUBLIC_SUPABASE_URL")


@pytest.fixture(scope="module")
def supabase_anon_key() -> str:
    return _required_env("NEXT_PUBLIC_SUPABASE_ANON_KEY")


@pytest.fixture(scope="module")
def user_credentials() -> tuple[str, str]:
    return (_required_env("TEST_USER_EMAIL"), _required_env("TEST_USER_PASSWORD"))


@pytest.fixture(scope="module")
def admin_credentials() -> tuple[str, str]:
    return (_required_env("TEST_ADMIN_EMAIL"), _required_env("TEST_ADMIN_PASSWORD"))


def test_valid_jwt_returns_user_and_role(
    supabase_url: str,
    supabase_anon_key: str,
    user_credentials: tuple[str, str],
) -> None:
    """A valid JWT returns the authenticated user + role from the API."""
    from supabase import create_client

    email, password = user_credentials
    supabase = create_client(supabase_url, supabase_anon_key)
    session = _login(email, password, supabase)
    jwt = session.access_token

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {jwt}"},
        )
    assert response.status_code == 200, response.text
    # The route serializes AuthUser directly (flat {id, email, role}).
    user = response.json()
    assert user.get("id") == session.user.id
    assert user.get("email") == email
    assert user.get("role") in {"user", "admin"}


def test_invalid_jwt_is_rejected(supabase_url: str, supabase_anon_key: str) -> None:
    """An invalid/missing JWT is rejected with 401."""
    with TestClient(app) as client:
        # Invalid token
        response_bad = client.get(
            "/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response_bad.status_code == 401

        # Missing token
        response_missing = client.get("/auth/me")
        assert response_missing.status_code == 401


def test_rls_authenticated_client_returns_own_row(
    supabase_url: str,
    supabase_anon_key: str,
    user_credentials: tuple[str, str],
) -> None:
    """CRITICAL REGRESSION: the returned Supabase client must return the
    user's OWN profile row under RLS.

    This is the exact bug from the TypeScript backend: an unauthenticated
    client would return empty/null for a SELECT on an RLS-protected table. Here
    we authenticate via the API (which builds an RLS-authenticated client) and
    confirm that querying ``profiles`` for the user id actually returns the
    user's own row (non-null).
    """
    from supabase import create_client

    email, password = user_credentials
    supabase = create_client(supabase_url, supabase_anon_key)
    session = _login(email, password, supabase)
    jwt = session.access_token
    user_id = session.user.id

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {jwt}"},
        )
        assert response.status_code == 200, response.text
        # The route returns AuthUser directly (flat shape).
        user = response.json()
        assert user["id"] == user_id

    # Now re-create an RLS-authenticated client the same way the service does,
    # and confirm the SELECT on the RLS-protected profiles table returns the
    # user's own row (the regression we're guarding against).
    import asyncio

    from app.auth.service import _create_authenticated_client
    from app.config import get_settings

    async def _query_own_row() -> dict | None:
        settings = get_settings()
        client = await _create_authenticated_client(settings, jwt)
        result = (
            await client.table("profiles")
            .select("id, email, full_name, role")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        return result.data

    row = asyncio.run(_query_own_row())
    assert row is not None, (
        "RLS regression: authenticated client returned null for the user's own "
        "profile row. This means the JWT was not attached to the Supabase client."
    )
    assert row["id"] == user_id
    assert row["role"] in {"user", "admin"}


def test_require_admin_rejects_non_admin(
    supabase_url: str,
    supabase_anon_key: str,
    admin_credentials: tuple[str, str],
    user_credentials: tuple[str, str],
) -> None:
    """require_admin rejects a non-admin user with 403, allows an admin."""
    from supabase import create_client

    # Non-admin user -> 403
    user_email, user_password = user_credentials
    supabase = create_client(supabase_url, supabase_anon_key)
    user_session = _login(user_email, user_password, supabase)
    with TestClient(app) as client:
        response_non_admin = client.get(
            "/auth/me/admin",
            headers={"Authorization": f"Bearer {user_session.access_token}"},
        )
        assert response_non_admin.status_code == 403, response_non_admin.text

    # Admin user -> 200
    admin_email, admin_password = admin_credentials
    admin_session = _login(admin_email, admin_password, supabase)
    with TestClient(app) as client:
        response_admin = client.get(
            "/auth/me/admin",
            headers={"Authorization": f"Bearer {admin_session.access_token}"},
        )
        assert response_admin.status_code == 200, response_admin.text
        assert response_admin.json()["role"] == "admin"
