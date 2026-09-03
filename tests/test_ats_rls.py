"""Regression tests: ATS report RLS verification (P1).

Verifies that ``resume_ats_analyses`` is protected by RLS at the schema level
(migration 009) and that the ATS report route delegates reads through the
authenticated (RLS) client — i.e. User A cannot read User B's ATS report
(presented as "not found / unauthorized") while a user CAN read their own.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_user

_MIGRATION = Path(__file__).resolve().parents[1] / "sql" / "migrations" / "009_resume_ats_analyses.sql"


def _ctx(user_id: str, jwt: str) -> AuthContext:
    return AuthContext(
        user=AuthUser(id=user_id, email=f"{user_id}@example.com"),
        supabase=None,  # type: ignore[arg-type]
        jwt=jwt,
    )


def test_ats_migration_enables_rls_with_ownership_policy():
    """Schema-level guarantee: RLS is enabled and SELECT is scoped by owner."""
    sql = _MIGRATION.read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in sql
    # A SELECT policy scoping rows by the authenticated resume owner.
    assert "CREATE POLICY \"Users can view own resume analyses\"" in sql
    assert "FOR SELECT" in sql
    assert "user_id = auth.uid()" in sql
    # Insert is owner-scoped too, so no cross-user writes.
    assert "FOR INSERT" in sql


def _report():
    return SimpleNamespace(
        id="report-1",
        resume_id="resume-A",
        version_id=None,
        job_title="Engineer",
        company="Acme",
        overall_score=80.0,
        keyword_match_score=80.0,
        skills_match_score=80.0,
        experience_relevance_score=80.0,
        qualification_match_score=80.0,
        structure_format_score=80.0,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def test_user_a_cannot_read_user_b_ats_report():
    """Attacker (user-A) reading a report owned by user-B → 404/unauthorized."""
    client = TestClient(app)
    mock_repo = MagicMock()
    # RLS hides the cross-user row: authenticated client returns nothing.
    mock_repo.get_report.return_value = None

    app.dependency_overrides[get_current_user] = lambda: _ctx("user-A", "jwt-A")
    try:
        with patch("app.api.routes.ats.ats_repo", mock_repo):
            resp = client.get(
                "/api/ats/reports/report-1",
                headers={"Authorization": "Bearer jwt-A"},
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 404
    # The repo was queried under the caller's authenticated JWT (RLS), so a
    # service-role bypass would never be observable by a non-owner.
    assert mock_repo.get_report.call_args.kwargs == {"jwt": "jwt-A"}


def test_user_can_read_own_ats_report():
    """Owner (user-A) reading their own report → 200 with the report payload."""
    client = TestClient(app)
    mock_repo = MagicMock()
    mock_repo.get_report.return_value = _report()
    mock_resume_repo = MagicMock()
    mock_resume_repo.return_value.get_resume.return_value = {"id": "resume-A", "user_id": "user-A"}

    app.dependency_overrides[get_current_user] = lambda: _ctx("user-A", "jwt-A")
    try:
        with patch("app.api.routes.ats.ats_repo", mock_repo), patch(
            "app.api.routes.ats.ResumeRepository", mock_resume_repo
        ):
            resp = client.get(
                "/api/ats/reports/report-1",
                headers={"Authorization": "Bearer jwt-A"},
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    assert resp.json()["id"] == "report-1"
    assert mock_repo.get_report.call_args.kwargs == {"jwt": "jwt-A"}


def test_user_b_cannot_read_user_a_ats_report_via_idor():
    """Defense in depth: Even if ats_repo returned User A's report, resume check blocks User B."""
    client = TestClient(app)
    mock_repo = MagicMock()
    mock_repo.get_report.return_value = _report()
    mock_resume_repo = MagicMock()
    # User B does NOT own resume-A
    mock_resume_repo.return_value.get_resume.return_value = None

    app.dependency_overrides[get_current_user] = lambda: _ctx("user-B", "jwt-B")
    try:
        with patch("app.api.routes.ats.ats_repo", mock_repo), patch(
            "app.api.routes.ats.ResumeRepository", mock_resume_repo
        ):
            resp = client.get(
                "/api/ats/reports/report-1",
                headers={"Authorization": "Bearer jwt-B"},
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 404


def test_user_b_cannot_list_user_a_ats_history():
    """User B cannot list historical ATS reports for User A's resume."""
    client = TestClient(app)
    mock_resume_repo = MagicMock()
    mock_resume_repo.return_value.get_resume.return_value = None

    app.dependency_overrides[get_current_user] = lambda: _ctx("user-B", "jwt-B")
    try:
        with patch("app.api.routes.ats.ResumeRepository", mock_resume_repo):
            resp = client.get(
                "/api/ats/resume/resume-A/history",
                headers={"Authorization": "Bearer jwt-B"},
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 404