"""Tests for the dashboard telemetry endpoint.

These unit tests mock the auth dependency and the DashboardService class:
- ``get_current_user`` is overridden to return a fixed AuthContext.
- ``DashboardService`` is patched so its async method returns deterministic
  telemetry without touching Supabase.
"""

from __future__ import annotations

from typing import Iterator, List, Optional

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_user


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def authenticator() -> AuthContext:
    return AuthContext(
        user=AuthUser(id="test-user-id", email="test@example.com", role="user"),
        supabase=MagicMock(),
        jwt="test-token",
    )


@pytest.fixture
def override_auth(authenticator: AuthContext) -> Iterator[None]:
    app.dependency_overrides[get_current_user] = lambda: authenticator
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mock_service() -> MagicMock:
    with patch("app.api.routes.dashboard.DashboardService") as svc_cls:
        instance = svc_cls.return_value
        instance.get_user_telemetry = AsyncMock()
        yield instance


def _default_telemetry() -> dict:
    return {
        "total_resumes": 3,
        "tailored_versions": 2,
        "applications_tracked": 5,
        "average_ats_score": 78.5,
        "active_jobs_in_queue": 1,
        "activity_timeline": [
            {
                "action": "resume_created",
                "description": "Created resume 'My Resume'",
                "timestamp": "2024-01-02T00:00:00",
                "metadata": {"resume_id": "resume-1", "parse_status": "completed"},
            },
            {
                "action": "application_tracked",
                "description": "Tracking Software Engineer at Acme Corp",
                "timestamp": "2024-01-01T00:00:00",
                "metadata": {"application_id": "app-1"},
            },
        ],
    }


def test_get_dashboard_authenticated(
    client: TestClient, override_auth, mock_service: MagicMock
) -> None:
    mock_service.get_user_telemetry.return_value = _default_telemetry()

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["total_resumes"] == 3
    assert payload["data"]["tailored_versions"] == 2
    assert payload["data"]["applications_tracked"] == 5
    assert payload["data"]["average_ats_score"] == 78.5
    assert payload["data"]["active_jobs_in_queue"] == 1
    assert len(payload["data"]["activity_timeline"]) == 2
    mock_service.get_user_telemetry.assert_awaited_once_with("test-user-id")


def test_get_dashboard_unauthenticated_returns_401(client: TestClient) -> None:
    response = client.get("/api/dashboard")

    assert response.status_code == 401


def test_get_dashboard_empty_state(
    client: TestClient, override_auth, mock_service: MagicMock
) -> None:
    mock_service.get_user_telemetry.return_value = {
        "total_resumes": 0,
        "tailored_versions": 0,
        "applications_tracked": 0,
        "average_ats_score": None,
        "active_jobs_in_queue": 0,
        "activity_timeline": [],
    }

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["total_resumes"] == 0
    assert payload["data"]["average_ats_score"] is None
    assert payload["data"]["activity_timeline"] == []


def test_get_dashboard_schema_validation(
    client: TestClient, override_auth, mock_service: MagicMock
) -> None:
    mock_service.get_user_telemetry.return_value = _default_telemetry()

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    data = payload["data"]
    assert isinstance(data["total_resumes"], int)
    assert isinstance(data["tailored_versions"], int)
    assert isinstance(data["applications_tracked"], int)
    assert data["average_ats_score"] is None or isinstance(data["average_ats_score"], (int, float))
    assert isinstance(data["active_jobs_in_queue"], int)
    assert isinstance(data["activity_timeline"], list)
