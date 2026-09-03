"""Asymmetric (JWKS) verification of Supabase user access tokens.

Supabase signs the user ``access_token`` (the JWT the browser sends as
``Authorization: Bearer <token>``) with an ES256 private key. The public
signing keys are published by the project at::

    https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json

The legacy anon / service_role *API keys* are NOT user JWTs and are never used
as signing/verification secrets here. This module verifies the JWT signature
locally against the project's JWKS public keys (selected by the JWT header
``kid``) and then validates the issuer, audience, and expiry/issued-at claims.

This replaces the previous ``supabase.auth.get_user(jwt)`` approach, which
performed a server-side round-trip to GoTrue presenting the legacy anon key as
the ``apikey`` header. Once the legacy API keys were disabled, GoTrue rejected
that request with ``"Legacy API keys are disabled"`` and every authenticated
request returned ``401``. Local asymmetric verification has no such dependency.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional
import uuid

import jwt as pyjwt

logger = logging.getLogger(__name__)

# GoTrue's default value for the JWT ``aud`` claim on user access tokens.
DEFAULT_SUPABASE_JWT_AUDIENCE = "authenticated"

# Algorithms accepted for Supabase user access tokens (confirmed against the
# project JWKS: ``kty=EC``, ``crv=P-256``, ``alg=ES256``, ``use=sig``).
ALLOWED_ALGORITHMS = ["ES256"]

# Claims that must be present on every verified Supabase user access token.
REQUIRED_CLAIMS = ["exp", "iss", "aud", "sub"]


class JWTVerificationError(Exception):
    """Raised when a user access token fails verification."""


# A signing-key provider: given the raw JWT, returns an object exposing a
# ``.key`` attribute with the verification public key for the token's ``kid``.
# This mirrors the ``jwt.PyJWKClient.get_signing_key_from_jwt`` contract so the
# real implementation and deterministic test doubles are interchangeable.
SigningKeyProvider = Callable[[str], object]


def derive_jwks_url(supabase_url: str) -> str:
    """Derive the Supabase project's JWKS endpoint from its project URL.

    ``supabase_url`` is e.g. ``https://<project-ref>.supabase.co``; the JWKS
    document lives under the ``/auth/v1`` gateway path.
    """
    return f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


class JWKSVerifier:
    """Verify Supabase user access tokens against the project's JWKS.

    The default signing-key provider uses ``jwt.PyJWKClient`` (fetches the
    JWKS once and caches it, honoring HTTP caching directives). For
    deterministic unit tests, pass your own ``get_signing_key`` provider.
    """

    def __init__(
        self,
        supabase_url: str,
        *,
        audience: str = DEFAULT_SUPABASE_JWT_AUDIENCE,
        jwks_url: Optional[str] = None,
        get_signing_key: Optional[SigningKeyProvider] = None,
    ) -> None:
        self.supabase_url = supabase_url.rstrip("/")
        self.expected_issuer = f"{self.supabase_url}/auth/v1"
        self.jwks_url = jwks_url or derive_jwks_url(self.supabase_url)
        self.expected_audience = audience

        if get_signing_key is None:
            self._jwks_client: Optional[pyjwt.PyJWKClient] = pyjwt.PyJWKClient(
                self.jwks_url
            )
            self._get_signing_key: SigningKeyProvider = (
                self._jwks_client.get_signing_key_from_jwt
            )
        else:
            self._jwks_client = None
            self._get_signing_key = get_signing_key

    def verify(self, token: str) -> dict:
        """Verify ``token`` and return its verified claims.

        Raises :class:`JWTVerificationError` on any failure — malformed token,
        unexpected algorithm, unresolvable/unknown ``kid``, bad signature,
        expired token, wrong issuer, or wrong audience.
        """
        if not token or not isinstance(token, str):
            raise JWTVerificationError("Missing or invalid token")

        # Read only the header (never trust the payload) to pre-check the
        # algorithm and locate the signing key by ``kid``.
        try:
            header = pyjwt.get_unverified_header(token)
        except pyjwt.InvalidTokenError as exc:
            raise JWTVerificationError(f"Could not read JWT header: {exc}") from exc

        algorithm = header.get("alg")
        if algorithm not in ALLOWED_ALGORITHMS:
            raise JWTVerificationError(f"Unexpected JWT algorithm: {algorithm!r}")

        # Resolve the verification public key (covers an unknown/missing ``kid``
        # and any JWKS fetch/cache failure).
        try:
            key = self._get_signing_key(token).key
        except Exception as exc:  # noqa: BLE001 - normalized to JWTVerificationError
            raise JWTVerificationError(
                f"Could not resolve signing key: {exc}"
            ) from exc

        try:
            claims = pyjwt.decode(
                token,
                key,
                algorithms=ALLOWED_ALGORITHMS,
                issuer=self.expected_issuer,
                audience=self.expected_audience,
                options={
                    "require": REQUIRED_CLAIMS,
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_nbf": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except pyjwt.ExpiredSignatureError as exc:
            raise JWTVerificationError("Token has expired") from exc
        except pyjwt.InvalidAudienceError as exc:
            raise JWTVerificationError(f"Invalid token audience: {exc}") from exc
        except pyjwt.InvalidIssuerError as exc:
            raise JWTVerificationError(f"Invalid token issuer: {exc}") from exc
        except pyjwt.InvalidTokenError as exc:
            raise JWTVerificationError(f"Token verification failed: {exc}") from exc

        sub = claims.get("sub")
        if not sub:
            raise JWTVerificationError("Token is missing the `sub` claim")
        try:
            uuid.UUID(str(sub))
        except (ValueError, TypeError, AttributeError) as exc:
            raise JWTVerificationError(
                f"Malformed token subject: {sub!r} is not a valid UUID"
            ) from exc
        return claims