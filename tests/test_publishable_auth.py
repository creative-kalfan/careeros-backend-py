import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.config import Settings
from app.auth.service import (
    _create_authenticated_client,
    _get_or_create_profile,
    ProfileRow,
    AuthContext,
    AuthUser,
    AuthError,
)
from app.dependencies import get_current_user, get_current_admin
from app.main import app


@pytest.mark.asyncio
async def test_supabase_client_creation_and_headers():
    publishable_key = "sb_publishable_proj1234567890abcdef"
    jwt = "test.user.jwt"
    settings = Settings(
        NEXT_PUBLIC_SUPABASE_URL="https://example.supabase.co",
        NEXT_PUBLIC_SUPABASE_ANON_KEY=publishable_key,
        SUPABASE_SERVICE_ROLE_KEY="dummy_service_role",
    )

    # 1. Supabase client creation with sb_publishable_... key
    client = await _create_authenticated_client(settings, jwt)
    assert client is not None
    assert client.supabase_key == publishable_key
    assert client.supabase_key.startswith("sb_publishable_")

    # 2. Authenticated user JWT attached to client options
    assert client.options.headers.get("Authorization") == f"Bearer {jwt}"

    # 3. PostgREST request headers inspection
    query = client.table("profiles").select("id, email")
    headers = query.request.headers
    assert headers.get("apikey") == publishable_key
    assert headers.get("authorization") == f"Bearer {jwt}"
    assert headers.get("authorization") != f"Bearer {publishable_key}"


@pytest.mark.asyncio
async def test_profile_lookup_existing():
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_eq = MagicMock()
    mock_maybe_single = MagicMock()

    mock_supabase.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_select.eq.return_value = mock_eq
    mock_eq.maybe_single.return_value = mock_maybe_single

    mock_execute = AsyncMock()
    mock_execute.return_value.data = {
        "id": "u1",
        "email": "u1@test.com",
        "full_name": "User One",
        "role": "user",
    }
    mock_maybe_single.execute = mock_execute

    profile = await _get_or_create_profile(
        mock_supabase,
        {"id": "u1", "email": "u1@test.com", "user_metadata": {}},
    )
    assert profile.id == "u1" and profile.email == "u1@test.com"
    mock_table.insert.assert_not_called()


@pytest.mark.asyncio
async def test_profile_auto_creation_when_missing():
    mock_supabase = MagicMock()
    mock_table = MagicMock()

    mock_supabase.table.return_value = mock_table

    mock_select = MagicMock()
    mock_eq = MagicMock()
    mock_maybe_single = MagicMock()
    mock_table.select.return_value = mock_select
    mock_select.eq.return_value = mock_eq
    mock_eq.maybe_single.return_value = mock_maybe_single

    call_count = 0
    async def mock_lookup_exec():
        nonlocal call_count
        call_count += 1
        res = MagicMock()
        if call_count == 1:
            res.data = None
        else:
            res.data = {
                "id": "u2",
                "email": "u2@test.com",
                "full_name": "New User",
                "role": "user",
            }
        return res

    mock_maybe_single.execute = mock_lookup_exec
    mock_insert = MagicMock()
    mock_insert_exec = AsyncMock()
    mock_insert.execute = mock_insert_exec
    mock_table.insert.return_value = mock_insert

    profile2 = await _get_or_create_profile(
        mock_supabase,
        {
            "id": "u2",
            "email": "u2@test.com",
            "user_metadata": {"full_name": "New User"},
        },
    )
    assert profile2.id == "u2" and profile2.full_name == "New User"
    mock_table.insert.assert_called_once()


def test_api_profile_me_unauthorized_missing_token():
    with TestClient(app) as client:
        r_no_auth = client.get("/api/profile/me")
        assert r_no_auth.status_code == 401


def test_api_profile_me_unauthorized_malformed_token():
    with TestClient(app) as client:
        r_bad_auth = client.get("/api/profile/me", headers={"Authorization": "Bearer not-a-valid-token"})
        assert r_bad_auth.status_code == 401


def test_api_profile_me_authenticated():
    mock_auth = AuthContext(
        user=AuthUser(id="usr-123", email="usr@example.com", role="user"),
        supabase=MagicMock(),
        jwt="valid.jwt.token",
    )
    with patch("app.api.routes.profile.ProfileRepository") as mock_repo_cls:
        repo = mock_repo_cls.return_value
        from app.models.profile import UserProfile

        repo.aget_profile = AsyncMock(
            return_value=UserProfile.from_db_row(
                {
                    "id": "usr-123",
                    "email": "usr@example.com",
                    "full_name": "Test User",
                    "role": "user",
                    "skills": ["python"],
                }
            )
        )
        app.dependency_overrides[get_current_user] = lambda: mock_auth
        try:
            with TestClient(app) as client:
                r_me = client.get("/api/profile/me", headers={"Authorization": "Bearer valid.jwt.token"})
                assert r_me.status_code == 200
                data = r_me.json()
                assert data["success"] is True
                assert data["data"]["id"] == "usr-123"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_auth_behavior():
    mock_request = MagicMock()
    user_context = AuthContext(
        user=AuthUser(id="u-normal", email="normal@test.com", role="user"),
        supabase=MagicMock(),
        jwt="token",
    )
    admin_context = AuthContext(
        user=AuthUser(id="u-admin", email="admin@test.com", role="admin"),
        supabase=MagicMock(),
        jwt="token",
    )

    with patch("app.dependencies.get_current_user", AsyncMock(return_value=user_context)):
        with pytest.raises(AuthError) as exc_info:
            await get_current_admin(mock_request)
        assert exc_info.value.status_code == 403

    with patch("app.dependencies.get_current_user", AsyncMock(return_value=admin_context)):
        res = await get_current_admin(mock_request)
        assert res.user.role == "admin"
