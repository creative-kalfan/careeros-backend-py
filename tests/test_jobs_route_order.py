"""Tests verifying route ordering and dispatch in the Jobs API router."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from app.main import app
from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_user


def test_jobs_route_ordering_saved_before_id():
    """Verify GET /jobs/saved route is declared before GET /jobs/{job_id}."""
    routes = [route for route in app.routes if hasattr(route, "path")]
    jobs_routes = [r for r in routes if r.path.startswith("/jobs")]

    saved_index = next((i for i, r in enumerate(jobs_routes) if r.path == "/jobs/saved"), -1)
    job_id_index = next((i for i, r in enumerate(jobs_routes) if r.path == "/jobs/{job_id}"), -1)

    assert saved_index != -1, "GET /jobs/saved route must exist"
    assert job_id_index != -1, "GET /jobs/{job_id} route must exist"
    assert saved_index < job_id_index, (
        f"Route ordering bug: /jobs/saved (index {saved_index}) must precede "
        f"/jobs/{{job_id}} (index {job_id_index})"
    )


def test_jobs_route_ordering_personalized_before_id():
    """Verify GET /jobs/personalized is declared before GET /jobs/{job_id}."""
    routes = [route for route in app.routes if hasattr(route, "path")]
    jobs_routes = [r for r in routes if r.path.startswith("/jobs")]

    pers_index = next((i for i, r in enumerate(jobs_routes) if r.path == "/jobs/personalized"), -1)
    job_id_index = next((i for i, r in enumerate(jobs_routes) if r.path == "/jobs/{job_id}"), -1)

    assert pers_index != -1
    assert pers_index < job_id_index


def test_get_saved_jobs_endpoint():
    """Verify calling /jobs/saved dispatches to list_saved_jobs handler, not get_job."""
    client = TestClient(app)
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
        {"id": "saved-1", "job_id": "job-123", "user_id": "u-1"}
    ]

    mock_auth = AuthContext(
        user=AuthUser(id="u-1", email="test@example.com"),
        supabase=mock_supabase,
        jwt="dummy-jwt",
    )

    app.dependency_overrides[get_current_user] = lambda: mock_auth
    try:
        response = client.get("/jobs/saved")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 1
        assert data["data"][0]["job_id"] == "job-123"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
