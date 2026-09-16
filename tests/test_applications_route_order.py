"""Tests verifying route ordering and behavior in Applications API router."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from app.main import app
from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_user


def test_applications_route_ordering_stats_before_id():
    """Verify GET /applications/stats is declared before GET /applications/{application_id}."""
    app_routes = []
    for route in app.routes:
        if hasattr(route, "path") and route.path and route.path.startswith("/applications"):
            app_routes.append(route.path)
        orig = getattr(route, "original_router", None)
        if orig and getattr(orig, "prefix", "") == "/applications":
            app_routes.extend([sr.path for sr in getattr(orig, "routes", []) if hasattr(sr, "path")])

    stats_index = next((i for i, p in enumerate(app_routes) if p == "/applications/stats"), -1)
    app_id_index = next((i for i, p in enumerate(app_routes) if p == "/applications/{application_id}"), -1)

    assert stats_index != -1, "GET /applications/stats route must exist"
    assert app_id_index != -1, "GET /applications/{application_id} route must exist"
    assert stats_index < app_id_index, (
        f"Route ordering bug: /applications/stats (index {stats_index}) must precede "
        f"/applications/{{application_id}} (index {app_id_index})"
    )


def test_get_application_stats_endpoint():
    """Verify calling /applications/stats returns aggregate calculations and not a single app 404."""
    client = TestClient(app)
    mock_supabase = MagicMock()
    mock_res = MagicMock()
    mock_res.data = [
        {"id": "app-1", "status": "applied", "application_date": "2026-09-01"},
        {"id": "app-2", "status": "interview", "application_date": "2026-09-02"},
        {"id": "app-3", "status": "offer", "application_date": "2026-09-03"},
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute = AsyncMock(return_value=mock_res)

    mock_auth = AuthContext(
        user=AuthUser(id="user-xyz", email="user@example.com"),
        supabase=mock_supabase,
        jwt="dummy-jwt",
    )

    app.dependency_overrides[get_current_user] = lambda: mock_auth
    try:
        response = client.get("/applications/stats")
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        stats = payload["data"]
        assert stats["total"] == 3
        assert stats["applied"] == 1
        assert stats["interview"] == 1
        assert stats["offer"] == 1
        assert stats["interviewRate"] == 67
        assert stats["offerRate"] == 50
    finally:
        app.dependency_overrides.pop(get_current_user, None)
