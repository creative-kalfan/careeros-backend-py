"""Shared FastAPI dependencies.

Exposes two dependencies used throughout the app:
- ``get_current_user``: authenticates a Bearer JWT and returns an
  :class:`AuthContext` (user + RLS-authenticated Supabase client).
- ``get_current_admin``: wraps ``get_current_user`` with an admin role check.

Both raise :class:`AuthError`, which is translated to an HTTP response by the
exception handler registered in ``app.main``.
"""

from __future__ import annotations

from fastapi import Request

from app.auth.service import (
    AuthContext,
    AuthError,
    extract_bearer_token,
    require_authenticated_user,
)
from app.services.jobs.job_relevance_service import JobRelevanceService


async def get_current_user(request: Request) -> AuthContext:
    """Authenticate the current request from its ``Authorization`` header.

    Extracts the Bearer JWT, verifies it against Supabase, ensures a profile
    row exists, and returns an :class:`AuthContext` carrying an
    RLS-authenticated Supabase client. Raises ``AuthError(401)`` on any
    missing/invalid token.
    """
    authorization = request.headers.get("Authorization")
    jwt = extract_bearer_token(authorization)

    if not jwt:
        raise AuthError("Unauthorized", status_code=401)

    return await require_authenticated_user(jwt)


async def get_current_admin(request: Request) -> AuthContext:
    """Like ``get_current_user`` but additionally requires ``role == "admin"``.

    Raises ``AuthError(403)`` when the authenticated user is not an admin.
    """
    context = await get_current_user(request)
    if context.user.role != "admin":
        raise AuthError("Forbidden: Admin access required", status_code=403)
    return context


def get_job_relevance_service() -> JobRelevanceService:
    """Factory for JobRelevanceService dependency injection."""
    return JobRelevanceService()