"""Deterministic unit tests for Supabase asymmetric (JWKS) JWT verification.

No network access and no real credentials: the ES256 key pair is generated
in-test, and the JWKS fetch is replaced by an in-memory signing-key provider
with the same contract as ``jwt.PyJWKClient.get_signing_key_from_jwt``.
"""

from __future__ import annotations

import time
import uuid

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth.jwt_verify import (
    JWKSVerifier,
    JWTVerificationError,
    derive_jwks_url,
)

PROJECT_URL = "https://test-project-ref.supabase.co"


def _make_keypair(kid: str):
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_numbers = private_key.public_key().public_numbers()
    import base64

    def _b64_uint(n: int) -> str:
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "kid": kid,
        "use": "sig",
        "alg": "ES256",
        "x": _b64_uint(public_numbers.x),
        "y": _b64_uint(public_numbers.y),
    }
    return private_key, jwk


PRIVATE_KEY, JWK = _make_keypair(kid="test-kid-1")
_, OTHER_JWK = _make_keypair(kid="other-kid")


class FakeSigningKey:
    def __init__(self, jwk: dict) -> None:
        self.key = pyjwt.PyJWK.from_dict(jwk).key
        self.kid = jwk["kid"]


def make_provider(jwks: list[dict]):
    """Signing-key provider mirroring PyJWKClient.get_signing_key_from_jwt."""

    def _get_signing_key(token: str) -> FakeSigningKey:
        header = pyjwt.get_unverified_header(token)
        for jwk in jwks:
            if jwk.get("kid") == header.get("kid"):
                return FakeSigningKey(jwk)
        raise pyjwt.PyJWKClientError("Unable to find a signing key that matches")

    return _get_signing_key


def make_verifier(**kwargs) -> JWKSVerifier:
    return JWKSVerifier(
        PROJECT_URL,
        get_signing_key=make_provider([JWK, OTHER_JWK]),
        **kwargs,
    )


def make_token(
    private_key=PRIVATE_KEY,
    *,
    kid: str = "test-kid-1",
    issuer: str | None = None,
    audience: str = "authenticated",
    subject: str | None = None,
    expires_in: int = 3600,
    alg: str = "ES256",
    headers: dict | None = None,
    extra_claims: dict | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "iss": issuer if issuer is not None else f"{PROJECT_URL}/auth/v1",
        "aud": audience,
        "sub": subject or str(uuid.uuid4()),
        "email": "user@example.com",
        "role": "authenticated",
        "iat": now,
        "exp": now + expires_in,
    }
    payload.update(extra_claims or {})
    hdr = {"alg": alg, "typ": "JWT", "kid": kid}
    hdr.update(headers or {})
    key: object = private_key
    if alg == "HS256":
        key = "not-a-real-signing-secret"  # alg is rejected before verification
    return pyjwt.encode(payload, key, algorithm=alg, headers=hdr)


def test_derive_jwks_url() -> None:
    assert derive_jwks_url(PROJECT_URL) == (
        f"{PROJECT_URL}/auth/v1/.well-known/jwks.json"
    )
    assert derive_jwks_url(PROJECT_URL + "/") == (
        f"{PROJECT_URL}/auth/v1/.well-known/jwks.json"
    )


def test_valid_es256_token_authenticates() -> None:
    claims = make_verifier().verify(make_token())
    assert claims["iss"] == f"{PROJECT_URL}/auth/v1"
    assert claims["aud"] == "authenticated"
    assert claims["sub"]


def test_invalid_signature_rejected() -> None:
    # Signed by a key that is NOT in the JWKS.
    other_private, _ = _make_keypair("test-kid-1")
    token = make_token(private_key=other_private)
    with pytest.raises(JWTVerificationError):
        make_verifier().verify(token)


def test_unknown_kid_rejected() -> None:
    token = make_token(kid="unknown-kid")
    with pytest.raises(JWTVerificationError):
        make_verifier().verify(token)


def test_expired_token_rejected() -> None:
    token = make_token(expires_in=-60)
    with pytest.raises(JWTVerificationError):
        make_verifier().verify(token)


def test_wrong_issuer_rejected() -> None:
    token = make_token(issuer="https://evil.example.com/auth/v1")
    with pytest.raises(JWTVerificationError):
        make_verifier().verify(token)


def test_wrong_audience_rejected() -> None:
    token = make_token(audience="not-authenticated")
    with pytest.raises(JWTVerificationError):
        make_verifier().verify(token)


def test_missing_authorization_shape_rejected() -> None:
    # Empty / non-string tokens are rejected without touching the JWKS.
    with pytest.raises(JWTVerificationError):
        make_verifier().verify("")
    with pytest.raises(JWTVerificationError):
        make_verifier().verify(None)


def test_malformed_jwt_rejected() -> None:
    for bad in ("not-a-real-token", "a.b", "aaa.bbb.ccc", "...."):
        with pytest.raises(JWTVerificationError):
            make_verifier().verify(bad)


def test_malformed_subject_rejected() -> None:
    for bad_sub in ("not-a-uuid", "admin", "12345", "../../etc/passwd", "xyz"):
        token = make_token(subject=bad_sub)
        with pytest.raises(JWTVerificationError) as excinfo:
            make_verifier().verify(token)
        assert "not a valid UUID" in str(excinfo.value)


def test_unexpected_algorithm_rejected() -> None:
    # HS256 is a valid JWT alg but NOT allowed for Supabase user tokens here.
    token = make_token(alg="HS256")
    with pytest.raises(JWTVerificationError):
        make_verifier().verify(token)


def test_service_verify_jwt_maps_error_to_auth_error() -> None:
    """service._verify_jwt converts JWTVerificationError into AuthError(401)."""
    import asyncio

    from app.auth.service import AuthError, _verify_jwt

    class DummyClient:
        pass

    with pytest.raises(AuthError) as excinfo:
        asyncio.run(_verify_jwt(DummyClient(), "not-a-real-token"))
    assert excinfo.value.status_code == 401


def test_service_verify_jwt_extracts_verified_sub(monkeypatch) -> None:
    """A valid token yields id == sub from the verified claims, not user input.

    The real ``JWKSVerifier`` (network-backed PyJWKClient) is replaced with a
    stub that returns pre-verified claims, keeping this unit test offline.
    The stub mirrors the real contract: raise JWTVerificationError on failure.
    """
    import asyncio

    import app.auth.service as service_module
    from app.auth.jwt_verify import JWTVerificationError

    class StubVerifier:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def verify(self, token: str) -> dict:
            # Only accept the token that our make_token() produced.
            try:
                return pyjwt.decode(
                    token,
                    PRIVATE_KEY.public_key(),
                    algorithms=["ES256"],
                    issuer=f"{PROJECT_URL}/auth/v1",
                    audience="authenticated",
                )
            except pyjwt.InvalidTokenError as exc:
                raise JWTVerificationError(str(exc)) from exc

    monkeypatch.setattr("app.auth.jwt_verify.JWKSVerifier", StubVerifier)

    class DummyClient:
        pass

    sub = str(uuid.uuid4())
    user = asyncio.run(
        service_module._verify_jwt(DummyClient(), make_token(subject=sub))
    )
    assert user["id"] == sub
    assert user["email"] == "user@example.com"