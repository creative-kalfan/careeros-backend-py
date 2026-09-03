"""Tests for profile API endpoints.

These unit tests mock the auth dependency and the ProfileRepository class:
- ``get_current_user`` is overridden to return a fixed AuthContext.
- ``ProfileRepository`` is patched so its async methods (aget_profile /
  aupdate_profile) return deterministic profiles without touching Supabase.

Authorization for other users / RLS is exercised live in test_auth.py; here we
verify the API contract and that the user id in requests cannot override the
authenticated identity.
"""

from __future__ import annotations

from typing import Iterator, List, Optional

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.auth.service import AuthContext, AuthUser
from app.models.profile import UserProfile
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
    """Override the auth dependency to return a fixed authenticated user."""
    app.dependency_overrides[get_current_user] = lambda: authenticator
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mock_repo() -> Iterator[MagicMock]:
    """Patch ProfileRepository so routes use deterministic async methods."""
    with patch("app.api.routes.profile.ProfileRepository") as repo_cls:
        instance = repo_cls.return_value
        instance.aget_profile = AsyncMock()
        instance.aupdate_profile = AsyncMock()
        yield instance


@pytest.fixture
def base_row() -> dict:
    return {
        "id": "test-user-id",
        "email": "test@example.com",
        "full_name": "Test User",
        "role": "user",
        "current_role": None,
        "desired_role": None,
        "skills": [],
        "location": None,
        "preferred_locations": [],
        "remote_preference": None,
        "preferred_companies": [],
        "salary_expectation_min": None,
        "salary_expectation_max": None,
        "salary_currency": "USD",
        "experience": None,
        "education": [],
    }


# ---------------------------------------------------------------------------
# GET /api/profile/me
# ---------------------------------------------------------------------------


def test_get_profile_authenticated(
    client: TestClient, override_auth, mock_repo: MagicMock, base_row: dict
) -> None:
    """Authenticated users can fetch their profile."""
    row = {**base_row, "desired_role": "Software Engineer", "skills": ["python"]}
    mock_repo.aget_profile.return_value = UserProfile.from_db_row(row)

    response = client.get("/api/profile/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["id"] == "test-user-id"
    assert payload["data"]["desired_role"] == "Software Engineer"
    assert payload["data"]["skills"] == ["python"]
    mock_repo.aget_profile.assert_awaited_once_with("test-user-id")


def test_get_profile_unauthenticated_returns_401(client: TestClient) -> None:
    """Unauthenticated requests are rejected with 401."""
    response = client.get("/api/profile/me")

    assert response.status_code == 401


def test_get_profile_not_found_returns_404(
    client: TestClient, override_auth, mock_repo: MagicMock
) -> None:
    """A missing profile row returns 404."""
    mock_repo.aget_profile.return_value = None

    response = client.get("/api/profile/me")

    assert response.status_code == 404
    payload = response.json()
    assert payload["success"] is False
    assert "Profile not found" in payload["error"]["message"]


# ---------------------------------------------------------------------------
# PATCH /api/profile/me
# ---------------------------------------------------------------------------


def test_patch_profile_updates_desired_role(
    client: TestClient,
    override_auth,
    mock_repo: MagicMock,
    base_row: dict,
) -> None:
    """desired_role can be updated."""
    existing = UserProfile.from_db_row(base_row)
    updated = UserProfile.from_db_row({**base_row, "desired_role": "Software Engineer"})
    mock_repo.aget_profile.return_value = existing
    mock_repo.aupdate_profile.return_value = updated

    response = client.patch("/api/profile/me", json={"desired_role": "Software Engineer"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["desired_role"] == "Software Engineer"
    # The update was scoped to the authenticated user id, never a client id.
    mock_repo.aupdate_profile.assert_awaited_once_with(
        "test-user-id", {"desired_role": "Software Engineer"}
    )


def test_patch_profile_accepts_experience_format(
    client: TestClient,
    override_auth,
    mock_repo: MagicMock,
    base_row: dict,
) -> None:
    """experience accepts the existing product format (e.g. '5 years')."""
    existing = UserProfile.from_db_row(base_row)
    updated = UserProfile.from_db_row({**base_row, "experience": "5 years"})
    mock_repo.aget_profile.return_value = existing
    mock_repo.aupdate_profile.return_value = updated

    response = client.patch("/api/profile/me", json={"experience": "5 years"})

    assert response.status_code == 200
    assert response.json()["data"]["experience"] == "5 years"


def test_patch_profile_partial_update_preserves_unspecified_fields(
    client: TestClient,
    override_auth,
    mock_repo: MagicMock,
    base_row: dict,
) -> None:
    """Patching one field must preserve other existing fields."""
    row = {
        **base_row,
        "desired_role": "Data Scientist",
        "skills": ["python", "ml"],
        "location": "Seattle",
    }
    existing = UserProfile.from_db_row(row)
    updated = UserProfile.from_db_row({**row, "desired_role": "Software Engineer"})
    mock_repo.aget_profile.return_value = existing
    mock_repo.aupdate_profile.return_value = updated

    response = client.patch("/api/profile/me", json={"desired_role": "Software Engineer"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["desired_role"] == "Software Engineer"
    assert data["skills"] == ["python", "ml"]
    assert data["location"] == "Seattle"
    # The update payload only contained the provided field.
    mock_repo.aupdate_profile.assert_awaited_once_with(
        "test-user-id", {"desired_role": "Software Engineer"}
    )


def test_patch_profile_cannot_change_user_id(
    client: TestClient,
    override_auth,
    mock_repo: MagicMock,
    base_row: dict,
) -> None:
    """A client-supplied id/user_id is never honored."""
    existing = UserProfile.from_db_row(base_row)
    updated = UserProfile.from_db_row({**base_row, "desired_role": "Software Engineer"})
    mock_repo.aget_profile.return_value = existing
    mock_repo.aupdate_profile.return_value = updated

    response = client.patch(
        "/api/profile/me",
        json={
            "desired_role": "Software Engineer",
            "id": "other-user-id",
            "user_id": "other-user-id",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == "test-user-id"
    # Neither id nor user_id reached the repository update.
    mock_repo.aupdate_profile.assert_awaited_once_with(
        "test-user-id", {"desired_role": "Software Engineer"}
    )


def test_patch_profile_invalid_data_returns_422(
    client: TestClient, override_auth, mock_repo: MagicMock
) -> None:
    """Invalid field types are rejected with a validation error."""
    response = client.patch("/api/profile/me", json={"skills": "not-a-list"})

    assert response.status_code == 422
    assert mock_repo.aupdate_profile.await_count == 0


def test_patch_profile_no_fields_returns_existing(
    client: TestClient,
    override_auth,
    mock_repo: MagicMock,
    base_row: dict,
) -> None:
    """An empty PATCH returns the current profile without writing."""
    existing = UserProfile.from_db_row({**base_row, "desired_role": "Software Engineer"})
    mock_repo.aget_profile.return_value = existing

    response = client.patch("/api/profile/me", json={})

    assert response.status_code == 200
    assert response.json()["data"]["desired_role"] == "Software Engineer"
    mock_repo.aupdate_profile.assert_not_called()


def test_patch_then_get_retrieves_updated_value(
    client: TestClient,
    override_auth,
    mock_repo: MagicMock,
    base_row: dict,
) -> None:
    """After a PATCH, a subsequent GET returns the updated value."""
    existing = UserProfile.from_db_row(base_row)
    updated = UserProfile.from_db_row({**base_row, "desired_role": "Software Engineer"})
    mock_repo.aget_profile.return_value = existing
    mock_repo.aupdate_profile.return_value = updated

    patch_response = client.patch(
        "/api/profile/me", json={"desired_role": "Software Engineer"}
    )
    assert patch_response.status_code == 200

    # Simulate the repository persisting the change: the second read returns
    # the updated row.
    mock_repo.aget_profile.return_value = updated
    get_response = client.get("/api/profile/me")

    assert get_response.status_code == 200
    assert get_response.json()["data"]["desired_role"] == "Software Engineer"
