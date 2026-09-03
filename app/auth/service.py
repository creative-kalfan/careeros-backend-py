"""Authentication service: JWT verification, profile lookup / auto-create,
and an RLS-authenticated Supabase client.

Mirrors the behavior of the TypeScript ``lib/auth.ts`` ``requireUser()`` /
``requireAdmin()`` but fixes the RLS bug from the original: the Supabase client
is created *with* the caller's JWT attached (``auth={"access_token": ...}``) so
that all subsequent queries run under the user's RLS context instead of silently
creating an unauthenticated client that returns empty results on RLS-protected
tables.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, EmailStr, Field

from supabase import acreate_client
from supabase._async.client import AsyncClient
from supabase.lib.client_options import AsyncClientOptions

from app.config import Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover
    from supabase._async.auth_client import AsyncSupabaseAuthClient

logger = logging.getLogger(__name__)


class AuthUser(BaseModel):
    """Serializable shape of an authenticated user returned by the API."""

    id: str
    email: EmailStr
    role: str = Field(default="user", pattern=r"^(user|admin)$")


@dataclass
class AuthContext:
    """Authenticated context: the user plus an RLS-authenticated Supabase client.

    Injected into routes via ``Depends(get_current_user)``. This is a plain
    dataclass (not a pydantic model) because the ``AsyncClient`` field cannot
    have a pydantic schema generated for it, and this object is never
    serialized to JSON — routes only expose ``context.user``.
    """

    user: AuthUser
    supabase: "AsyncClient"
    jwt: str


class ProfileRow(BaseModel):
    """The shape of a row from the public ``profiles`` table."""

    id: str
    email: str | None = None
    full_name: str | None = None
    role: str = "user"


class AuthError(Exception):
    """Raised when authentication or authorization fails."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def extract_bearer_token(authorization: str | None) -> str | None:
    """Extract the Bearer JWT from an Authorization header value, if present."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].strip().lower() == "bearer":
        token = parts[1].strip()
        return token or None
    return None


async def _create_authenticated_client(
    settings: Settings, jwt: str
) -> "AsyncClient":
    """Create a Supabase AsyncClient with the caller's JWT attached.

    Attaching ``access_token`` is **critical**: without it, the client is
    unauthenticated and any SELECT on an RLS-protected table (e.g.
    ``profiles``) silently returns empty results. The original TypeScript
    implementation hit exactly this bug.
    """
    options = AsyncClientOptions(
        auto_refresh_token=False,
        persist_session=False,
        headers={"Authorization": f"Bearer {jwt}"},
    )
    client = await acreate_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        options=options,
    )
    return client


async def _verify_jwt(
    supabase: "AsyncClient", jwt: str
) -> dict:
    """Verify the user access token locally via the project's JWKS.

    Previously this called ``supabase.auth.get_user(jwt)``, which performed a
    server-side round-trip to Supabase Auth (GoTrue) presenting the legacy
    anon key as the ``apikey`` header. Once the legacy API keys were disabled,
    GoTrue rejected that request with ``"Legacy API keys are disabled"`` and
    every authenticated request returned 401.

    Verification is now fully local and asymmetric: the token's ES256
    signature is checked against the project's published JWKS public keys
    (selected by ``kid``), and the issuer/audience/expiry claims are validated.
    The ``sb_secret_...`` API key is never used as a JWT verification secret —
    it is only used as the Supabase data-API credential when building the
    RLS-authenticated client.
    """
    from app.auth.jwt_verify import JWKSVerifier, JWTVerificationError

    try:
        verifier = JWKSVerifier(get_settings().supabase_url)
        claims = verifier.verify(jwt)
    except JWTVerificationError as exc:
        logger.warning("JWT verification failed: %s", exc)
        raise AuthError("Unauthorized", status_code=401) from exc

    return {
        "id": claims["sub"],
        "email": claims.get("email") or "",
        "user_metadata": claims.get("user_metadata") or {},
    }


async def _get_or_create_profile(
    supabase: "AsyncClient", user: dict
) -> ProfileRow:
    """Look up the user's profile row, auto-creating it if missing.

    Matching the original TS behavior: after a successful JWT verification, we
    look up the ``profiles`` row for this user id. Because the client carries
    the authenticated JWT, this SELECT is subject to RLS (``auth.uid() = id``),
    which returns exactly the caller's own row. If missing, we insert a row
    (allowed by the "Users can insert own profile" policy) and re-read it.
    """
    user_id = user["id"]
    email = user["email"] or ""
    metadata = user["user_metadata"] or {}
    full_name = (
        metadata.get("full_name")
        or metadata.get("name")
        or (email.split("@")[0] if email else "User")
    )

    select_result = (
        await supabase.table("profiles")
        .select("id, email, full_name, role")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )

    if select_result.data:
        return ProfileRow.model_validate(select_result.data)

    # No profile row yet — auto-create it (RLS policy allows self-insert).
    await (
        supabase.table("profiles")
        .insert(
            {
                "id": user_id,
                "email": email,
                "full_name": full_name,
                "role": "user",
            }
        )
        .execute()
    )

    # Re-read the row we just created.
    re_read = (
        await supabase.table("profiles")
        .select("id, email, full_name, role")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    if not re_read.data:
        raise AuthError(
            "Profile created but could not be re-read (check INSERT RLS policy)",
            status_code=401,
        )
    return ProfileRow.model_validate(re_read.data)


async def require_authenticated_user(jwt: str) -> AuthContext:
    """Verify a JWT, ensure a profile exists, and return an RLS-authenticated
    context (user + Supabase client). Raises ``AuthError`` on failure."""
    settings = get_settings()

    # Create the RLS-authenticated client FIRST so that every subsequent query
    # (profile lookup, auto-create, re-read) runs under the caller's RLS role.
    supabase = await _create_authenticated_client(settings, jwt)

    try:
        user = await _verify_jwt(supabase, jwt)
        profile = await _get_or_create_profile(supabase, user)

        return AuthContext(
            user=AuthUser(
                id=user["id"],
                email=user["email"],
                role=profile.role,
            ),
            supabase=supabase,
            jwt=jwt,
        )
    except AuthError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected error during authentication")
        raise AuthError("Unauthorized") from exc