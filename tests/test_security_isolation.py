"""Security and user isolation test suite (WS8)."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from app.main import app
from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_user


def test_user_cannot_access_other_user_application():
    """Verify application routes enforce user_id scoping on queries."""
    client = TestClient(app)
    mock_supabase = MagicMock()
    # Mock PostgREST returning empty data because query filters eq('user_id', auth.user.id)
    mock_res = MagicMock()
    mock_res.data = []
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute = AsyncMock(return_value=mock_res)

    mock_auth = AuthContext(
        user=AuthUser(id="attacker-user-id", email="attacker@example.com"),
        supabase=mock_supabase,
        jwt="attacker-jwt",
    )

    app.dependency_overrides[get_current_user] = lambda: mock_auth
    try:
        response = client.get("/applications/victim-application-id")
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Application not found"

        # Verify supabase query had eq("user_id", "attacker-user-id")
        mock_supabase.table.assert_called_with("applications")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_unauthorized_access_without_token():
    """Verify accessing protected routes without Bearer token returns 401 or 403."""
    client = TestClient(app)
    # Ensure no overrides
    app.dependency_overrides.pop(get_current_user, None)

    response = client.get("/applications")
    assert response.status_code == 401 or response.status_code == 403

    response = client.get("/api/resumes")
    assert response.status_code == 401 or response.status_code == 403

    response = client.get("/notifications")
    assert response.status_code == 401 or response.status_code == 403

    response = client.get("/api/profile/me")
    assert response.status_code == 401 or response.status_code == 403

    response = client.get("/recommendations")
    assert response.status_code == 401 or response.status_code == 403

    response = client.post("/api/ats/analyze", json={
        "resume_id": "r-1", "job_description": "jd"
    })
    assert response.status_code == 401 or response.status_code == 403

    response = client.get("/api/improvement/ats/rep-1/change-set")
    assert response.status_code == 401 or response.status_code == 403


def test_user_b_cannot_access_user_a_improvement_report():
    """Verify improvement report endpoints block User B from User A's report."""
    from unittest.mock import patch
    from types import SimpleNamespace

    client = TestClient(app)
    mock_report = SimpleNamespace(
        id="rep-A",
        resume_id="resume-A",
        requirement_analysis=[],
    )
    mock_ats_repo = MagicMock()
    mock_ats_repo.get_report.return_value = mock_report

    mock_resume_repo = MagicMock()
    # Attacker user-B does not own resume-A
    mock_resume_repo.return_value.get_resume.return_value = None

    mock_auth = AuthContext(
        user=AuthUser(id="user-B", email="attacker@example.com"),
        supabase=MagicMock(),
        jwt="token-B",
    )

    app.dependency_overrides[get_current_user] = lambda: mock_auth
    try:
        with patch("app.api.routes.improvement.ats_repo", mock_ats_repo), patch(
            "app.api.routes.improvement.ResumeRepository", mock_resume_repo
        ):
            resp = client.get("/api/improvement/ats/rep-A/change-set")
            assert resp.status_code == 404

            resp = client.get("/api/improvement/ats/rep-A/decisions")
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_user_cannot_analyze_mismatched_resume_version():
    """Verify ATS analysis rejects version belonging to a different resume."""
    from unittest.mock import patch

    client = TestClient(app)
    mock_resume_repo = MagicMock()
    mock_resume_repo.return_value.get_resume.return_value = {
        "id": "resume-1",
        "user_id": "user-1",
    }
    mock_resume_repo.return_value.get_version.return_value = {
        "id": "ver-2",
        "resume_id": "resume-2",  # Mismatch!
    }

    mock_auth = AuthContext(
        user=AuthUser(id="user-1", email="user1@example.com"),
        supabase=MagicMock(),
        jwt="token-1",
    )

    app.dependency_overrides[get_current_user] = lambda: mock_auth
    try:
        with patch("app.api.routes.ats.ResumeRepository", mock_resume_repo):
            resp = client.post(
                "/api/ats/analyze",
                json={
                    "resume_id": "resume-1",
                    "version_id": "ver-2",
                    "job_description": "Software engineer with Python and SQL",
                },
            )
            assert resp.status_code == 400
            msg = resp.json().get("error", {}).get("message") or resp.json().get("detail", "")
            assert "Version does not belong to this resume" in msg
    finally:
        app.dependency_overrides.pop(get_current_user, None)
