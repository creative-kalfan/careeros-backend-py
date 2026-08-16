"""Auth-related routes.

Exposes two endpoints that exercise the authentication dependencies:
- ``GET /auth/me``: returns the current authenticated user (requires JWT).
- ``GET /auth/me/admin``: returns the current user only if they are an admin.

These endpoints return only the serializable user payload — the RLS-authenticated
Supabase client stays inside the request's dependency context (available to any
route that depends on ``get_current_user``) but is never JSON-serialized.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_admin, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=AuthUser)
async def me(context: AuthContext = Depends(get_current_user)) -> AuthUser:
    """Return the authenticated user (requires a valid Bearer JWT)."""
    return context.user


@router.get("/me/admin", response_model=AuthUser)
async def me_admin(
    context: AuthContext = Depends(get_current_admin),
) -> AuthUser:
    """Return the authenticated user only if they are an admin (403 otherwise)."""
    return context.user