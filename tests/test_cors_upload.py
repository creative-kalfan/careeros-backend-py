"""CORS + resume upload endpoint regression tests.

Verifies that the CareerOS frontend development origin (http://localhost:8080)
is allowed, that preflight works, and that /api/resumes/register surfaces real
backend errors (with CORS headers) instead of header-less 500s that browsers
misreport as CORS failures.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

FRONTEND_ORIGIN = "http://localhost:8080"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_cors_allows_frontend_dev_origin(client: TestClient) -> None:
    resp = client.get("/health", headers={"Origin": FRONTEND_ORIGIN})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_cors_preflight_options_succeeds(client: TestClient) -> None:
    resp = client.options(
        "/api/resumes/register",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert "POST" in resp.headers["access-control-allow-methods"]


def test_cors_is_not_unrestricted(client: TestClient) -> None:
    resp = client.get("/health", headers={"Origin": "http://evil.example.com"})
    assert resp.headers.get("access-control-allow-origin") != "*"
    assert resp.headers.get("access-control-allow-origin") != "http://evil.example.com"


def test_cors_credentials_preserved(client: TestClient) -> None:
    resp = client.get("/health", headers={"Origin": FRONTEND_ORIGIN})
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_register_endpoint_reachable_and_unauthenticated_error_has_cors(
    client: TestClient,
) -> None:
    """Without a token the endpoint must return the standard 401 envelope —
    WITH CORS headers so the frontend sees a real auth error, not a CORS symptom."""
    resp = client.post(
        "/api/resumes/register",
        json={"storage_path": "user/x.pdf", "filename": "x.pdf"},
        headers={"Origin": FRONTEND_ORIGIN, "Content-Type": "application/json"},
    )
    assert resp.status_code in (401, 403)
    assert resp.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    body = resp.json()
    # AuthError handler returns {"detail": ...}; standard envelope is
    # {"success": false, "error": {...}}. Both are real, surfaced errors.
    assert body.get("success") is False or "detail" in body


def test_register_invalid_payload_returns_validation_error_with_cors(
    client: TestClient,
) -> None:
    resp = client.post(
        "/api/resumes/register",
        json={"unexpected": "payload"},
        headers={"Origin": FRONTEND_ORIGIN, "Content-Type": "application/json"},
    )
    # Auth dependency resolves before body validation, so an unauthenticated
    # invalid payload returns 401; the important guarantee is that the error
    # is a handled response WITH CORS headers (not a header-less 500).
    assert resp.status_code in (401, 422)
    assert resp.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_auth_context_exposes_jwt() -> None:
    """AuthContext must carry the caller's JWT (resume repositories rely on it)."""
    from app.auth.service import AuthContext, AuthUser

    context = AuthContext(
        user=AuthUser(id="u1", email="e@x.com", role="user"),
        supabase=None,  # type: ignore[arg-type]
        jwt="token-123",
    )
    assert context.jwt == "token-123"


def test_get_authenticated_client_attaches_bearer_header() -> None:
    from unittest.mock import patch

    from app.db.supabase import get_authenticated_client

    with patch("app.db.supabase.create_client") as mock_create:
        mock_create.return_value = object()
        get_authenticated_client("my-jwt")
        args, kwargs = mock_create.call_args
        options = args[2] if len(args) > 2 else kwargs.get("options")
        assert options.headers["Authorization"] == "Bearer my-jwt"


def test_cors_method_allowlist_not_wildcard() -> None:
    """P0 CORS hardening: allowlist is explicit, never `*`."""
    from app.main import ALLOWED_CORS_HEADERS, ALLOWED_CORS_METHODS

    assert "*" not in ALLOWED_CORS_METHODS
    assert "PUT" not in ALLOWED_CORS_METHODS  # PUT intentionally not allowed
    for m in ("GET", "POST", "PATCH", "DELETE", "OPTIONS"):
        assert m in ALLOWED_CORS_METHODS

    assert "*" not in ALLOWED_CORS_HEADERS
    assert {"Authorization", "Content-Type"} <= set(ALLOWED_CORS_HEADERS)


def test_cors_preflight_disallowed_method_not_granted(client: TestClient) -> None:
    resp = client.options(
        "/api/resumes/register",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    # PUT is outside the allowlist → the preflight is rejected (400) and PUT
    # is NOT echoed back in access-control-allow-methods.
    assert resp.status_code == 400
    assert "PUT" not in resp.headers.get("access-control-allow-methods", "")


def test_cors_preflight_rejects_header_outside_allowlist(client: TestClient) -> None:
    resp = client.options(
        "/api/resumes/register",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,X-Requested-With",
        },
    )
    allowed = (resp.headers.get("access-control-allow-headers") or "").lower()
    assert "x-requested-with" not in allowed


def test_cors_preflight_allows_known_headers_and_methods(client: TestClient) -> None:
    resp = client.options(
        "/api/resumes/register",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert "PATCH" in resp.headers["access-control-allow-methods"]
    allowed_headers = (resp.headers.get("access-control-allow-headers") or "").lower()
    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers
