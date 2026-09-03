"""Regression tests: optimization suggestion acceptance ownership (P0).

Verifies that ``accept_suggestion``:
  1. Fetches/looks up suggestions & sessions through the *authenticated* (RLS)
     client — never the service-role client — so a caller can only see the
     rows they own at the database policy layer.
  2. Enforces an explicit application-level ownership check (session's resume
     must belong to the authenticated user) in addition to RLS.
  3. User A cannot accept User B's suggestion (403).
  4. A legitimate owner can accept their own suggestion (success).
  5. Internal exception text is NOT leaked to clients (safe generic error).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, status

from app.api.routes.optimization import accept_suggestion
from app.auth.service import AuthContext, AuthUser
from app.models.resume import ResumeContent
from app.schemas.optimization import AcceptSuggestionRequest


def _ctx(user_id: str, jwt: str) -> AuthContext:
    return AuthContext(
        user=AuthUser(id=user_id, email=f"{user_id}@example.com"),
        supabase=None,  # type: ignore[arg-type]
        jwt=jwt,
    )


def _record(session_id: str) -> dict:
    return {
        "id": "sug-1",
        "session_id": session_id,
        "suggestion": {
            "type": "professional_summary",
            "status": "pending",
            "suggested_text": "Improved summary",
        },
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_legitimate_user_can_accept_own_suggestion():
    """Own-resume: session belongs to user-A, caller is user-A → success."""
    mock_repo = MagicMock()
    mock_repo.get_suggestion.return_value = _record("sess-A")
    mock_repo.get_session.return_value = {"id": "sess-A", "resume_id": "resume-A", "version_id": None}
    mock_repo.update_suggestion.return_value = True
    mock_repo.list_suggestions_for_session.return_value = []
    mock_repo.update_session.return_value = True

    mock_resume_cls = MagicMock()
    mock_resume_cls.return_value.get_resume.return_value = {
        "id": "resume-A",
        "user_id": "user-A",
        "content": ResumeContent().to_dict(),
    }

    payload = AcceptSuggestionRequest(session_id="sess-A", suggestion_id="sug-1")

    def fake_apply(content, suggestion, edited_text=None):
        content_copy = ResumeContent.from_dict(content.to_dict())
        content_copy.profile.summary = "Improved summary"
        return content_copy

    with patch("app.api.routes.optimization.optimization_repo", mock_repo), patch(
        "app.api.routes.optimization.ResumeRepository", mock_resume_cls
    ), patch("app.api.routes.optimization._apply_suggestion_to_content", fake_apply):
        result = await accept_suggestion(payload, _ctx("user-A", "jwt-A"), "jwt-A")

    assert result.success is True
    assert result.status in ("accepted", "edited")
    # All suggestion/session writes went through the authenticated RLS client.
    assert mock_repo.get_suggestion.call_args.kwargs == {"jwt": "jwt-A"}
    assert mock_repo.get_session.call_args.kwargs == {"jwt": "jwt-A"}
    assert mock_repo.update_suggestion.call_args.kwargs["jwt"] == "jwt-A"
    assert mock_repo.list_suggestions_for_session.call_args.kwargs == {"jwt": "jwt-A"}
    assert mock_repo.update_session.call_args.kwargs["jwt"] == "jwt-A"


@pytest.mark.asyncio
async def test_accept_error_does_not_leak_internal_details():
    """A backend exception must yield a safe generic message, not internal text."""
    mock_repo = MagicMock()
    mock_repo.get_suggestion.return_value = _record("sess-A")
    mock_repo.get_session.return_value = {"id": "sess-A", "resume_id": "resume-A", "version_id": None}
    mock_repo.update_suggestion.side_effect = RuntimeError(
        "psycopg error: connection refused at /var/lib/postgresql/data (secret-detail)"
    )

    mock_resume_cls = MagicMock()
    mock_resume_cls.return_value.get_resume.return_value = {
        "id": "resume-A",
        "user_id": "user-A",
        "content": ResumeContent().to_dict(),
    }

    payload = AcceptSuggestionRequest(session_id="sess-A", suggestion_id="sug-1")

    with patch("app.api.routes.optimization.optimization_repo", mock_repo), patch(
        "app.api.routes.optimization.ResumeRepository", mock_resume_cls
    ), patch(
        "app.api.routes.optimization._apply_suggestion_to_content",
        lambda c, s, edited_text=None: ResumeContent.from_dict(
            {"profile": {"summary": "Ignored here"}}
        ),
    ):
        with pytest.raises(HTTPException) as excinfo:
            await accept_suggestion(payload, _ctx("user-A", "jwt-A"), "jwt-A")

    assert excinfo.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert excinfo.value.detail == "Failed to accept suggestion"
    # Ensure no internal path / DB / exception text leaks into the response.
    assert "/var/lib" not in str(excinfo.value.detail)
    assert "secret" not in str(excinfo.value.detail)
    assert "connection refused" not in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_user_cannot_reject_other_user_suggestion():
    """Attacker (user-B) rejects user-A's suggestion → 403 Forbidden."""
    from app.api.routes.optimization import reject_suggestion
    from app.schemas.optimization import RejectSuggestionRequest

    mock_repo = MagicMock()
    mock_repo.get_suggestion.return_value = _record("sess-A")
    mock_repo.get_session.return_value = {"id": "sess-A", "resume_id": "resume-A"}

    mock_resume_cls = MagicMock()
    # User B does NOT own resume-A
    mock_resume_cls.return_value.get_resume.return_value = None

    payload = RejectSuggestionRequest(session_id="sess-A", suggestion_id="sug-1")

    with patch("app.api.routes.optimization.optimization_repo", mock_repo), patch(
        "app.api.routes.optimization.ResumeRepository", mock_resume_cls
    ):
        with pytest.raises(HTTPException) as excinfo:
            await reject_suggestion(payload, _ctx("user-B", "jwt-B"), "jwt-B")

    assert excinfo.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_legitimate_user_can_reject_own_suggestion():
    """Owner (user-A) successfully rejects their own suggestion."""
    from app.api.routes.optimization import reject_suggestion
    from app.schemas.optimization import RejectSuggestionRequest

    mock_repo = MagicMock()
    mock_repo.get_suggestion.return_value = _record("sess-A")
    mock_repo.get_session.return_value = {"id": "sess-A", "resume_id": "resume-A"}
    mock_repo.update_suggestion.return_value = True
    mock_repo.list_suggestions_for_session.return_value = []
    mock_repo.update_session.return_value = True

    mock_resume_cls = MagicMock()
    mock_resume_cls.return_value.get_resume.return_value = {"id": "resume-A", "user_id": "user-A"}

    payload = RejectSuggestionRequest(session_id="sess-A", suggestion_id="sug-1")

    with patch("app.api.routes.optimization.optimization_repo", mock_repo), patch(
        "app.api.routes.optimization.ResumeRepository", mock_resume_cls
    ):
        resp = await reject_suggestion(payload, _ctx("user-A", "jwt-A"), "jwt-A")

    assert resp.success is True
    assert resp.status == "rejected"