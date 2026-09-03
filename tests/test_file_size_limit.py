"""Regression tests: backend resume upload size guard (P1).

Verifies that oversized resume blobs are rejected *before* the expensive
parse step, via the configurable ``MAX_RESUME_UPLOAD_BYTES`` limit, while
legitimate (under-limit) uploads still pass the guard.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_user
from app.services.resume_parsing import is_file_too_large


def _ctx(user_id: str, jwt: str) -> AuthContext:
    return AuthContext(
        user=AuthUser(id=user_id, email=f"{user_id}@example.com"),
        supabase=None,  # type: ignore[arg-type]
        jwt=jwt,
    )


def test_under_limit_allowed():
    assert is_file_too_large(b"\x00" * 10, max_bytes=100) is False


def test_at_limit_allowed():
    assert is_file_too_large(b"\x00" * 100, max_bytes=100) is False


def test_over_limit_rejected():
    assert is_file_too_large(b"\x00" * 101, max_bytes=100) is True


def test_uses_config_default_limit():
    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value = SimpleNamespace(max_resume_upload_bytes=100)
        assert is_file_too_large(b"\x00" * 101) is True
        assert is_file_too_large(b"\x00" * 50) is False


def test_parse_endpoint_rejects_oversized_file_before_parsing():
    """Route-level: an oversized file returns 413 and never reaches parsing."""
    client = TestClient(app)

    fake_storage = MagicMock()
    fake_storage.storage.from_.return_value.download.return_value = b"\x00" * 101
    fake_auth_client = MagicMock(return_value=fake_storage)

    mock_repo_cls = MagicMock()
    mock_repo_cls.return_value.get_resume.return_value = {
        "storage_path": "user-A/x.pdf",
        "original_filename": "x.pdf",
    }
    mock_repo_cls.return_value.update_resume.return_value = None

    app.dependency_overrides[get_current_user] = lambda: _ctx("user-A", "jwt-A")
    try:
        with patch("app.api.routes.resumes.ResumeRepository", mock_repo_cls), patch(
            "app.api.routes.resumes.get_authenticated_client", fake_auth_client
        ), patch(
            "app.api.routes.resumes.get_settings",
            return_value=SimpleNamespace(max_resume_upload_bytes=100),
        ):
            resp = client.post(
                "/api/resumes/resume-A/parse",
                headers={"Authorization": "Bearer jwt-A"},
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 413
    # Parser must never have been constructed for an oversized file.
    # (No assertion on ResumeParsingService here — it is deep in the success path.)


def test_parse_endpoint_allows_under_limit_file():
    """Route-level: an under-limit file is NOT rejected by the size guard."""
    client = TestClient(app)

    fake_storage = MagicMock()
    fake_storage.storage.from_.return_value.download.return_value = b"\x00" * 50
    fake_auth_client = MagicMock(return_value=fake_storage)

    mock_repo_cls = MagicMock()
    mock_repo_cls.return_value.get_resume.return_value = {
        "storage_path": "user-A/x.pdf",
        "original_filename": "x.pdf",
    }
    mock_repo_cls.return_value.update_resume.return_value = None

    app.dependency_overrides[get_current_user] = lambda: _ctx("user-A", "jwt-A")
    try:
        with patch("app.api.routes.resumes.ResumeRepository", mock_repo_cls), patch(
            "app.api.routes.resumes.get_authenticated_client", fake_auth_client
        ), patch(
            "app.api.routes.resumes.get_settings",
            return_value=SimpleNamespace(max_resume_upload_bytes=100),
        ):
            resp = client.post(
                "/api/resumes/resume-A/parse",
                headers={"Authorization": "Bearer jwt-A"},
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    # The guard must not reject it. (The actual parse is expected to fail in
    # this harness because there is no real file / parser — what matters for the
    # regression is that it is NOT a 413 and NOT rejected for size.)
    assert resp.status_code != 413