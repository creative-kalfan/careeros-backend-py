"""RED tests for HIGH review findings: Optional import + AuthError envelope."""

from __future__ import annotations

import typing

import pytest
from fastapi.testclient import TestClient

from app.auth.service import AuthError
from app.main import app


def test_crawl_jobs_optional_resolves_in_type_hints() -> None:
    """get_type_hints must resolve Optional on worker signatures (F821 fix)."""
    import app.workers.jobs.crawl_jobs as m

    assert "Optional" in dir(m) or "Optional" in vars(m), "Optional not imported in crawl_jobs"
    typing.get_type_hints(m._resolve_company_scope)
    typing.get_type_hints(m._deactivate_after_success)
    typing.get_type_hints(m._dispatch_ingest)


def test_auth_401_uses_standard_envelope() -> None:
    """Unauthenticated request must return {success:false, error:{code,message}}."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/resumes/register",
        json={"storage_path": "user/x.pdf", "filename": "x.pdf"},
        headers={"Origin": "http://localhost:8080", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body.get("success") is False
    assert "detail" not in body
    assert isinstance(body["error"]["message"], str) and body["error"]["message"].strip()


@pytest.mark.asyncio
async def test_auth_error_handler_403_envelope() -> None:
    """Direct handler check: 403 preserves status + envelope shape."""
    from fastapi import Request

    from app.main import auth_error_handler

    scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
    req = Request(scope)
    resp = await auth_error_handler(req, AuthError("Forbidden: Admin access required", status_code=403))
    assert resp.status_code == 403
    import json

    body = json.loads(bytes(resp.body).decode())
    assert body == {"success": False, "error": {"code": "forbidden", "message": "Forbidden: Admin access required"}}
