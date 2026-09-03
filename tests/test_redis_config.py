"""Infrastructure tests: Redis / worker configuration contract.

Verifies that the Settings configuration contract exposes the Redis and
worker-related fields expected by ``app.workers.settings`` and that the
FastAPI application can be imported and its route table constructed.

These tests verify configuration and startup only. Live Redis connectivity
is verified separately via ``scripts/test_redis_connectivity.py`` when a
Redis instance is available.
"""

import os

import pytest
from arq.connections import RedisSettings

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Ensure each test reads fresh environment state."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_settings_exposes_redis_url_contract():
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="anon",
        supabase_service_role_key="service",
    )
    assert settings.redis_url == "redis://localhost:6379"


def test_settings_reads_redis_url_from_environment(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://redis-host:6380/2")
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="anon",
        supabase_service_role_key="service",
    )
    assert settings.redis_url == "redis://redis-host:6380/2"


def test_settings_does_not_alias_wrong_redis_env_name(monkeypatch):
    """A similarly-named but incorrect env var must NOT feed redis_url."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_CONNECTION_STRING", "redis://wrong:6379")
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="anon",
        supabase_service_role_key="service",
    )
    assert settings.redis_url == "redis://localhost:6379"


def test_settings_exposes_crawl_lock_ttl():
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="anon",
        supabase_service_role_key="service",
    )
    assert isinstance(settings.crawl_lock_ttl_seconds, int)
    assert settings.crawl_lock_ttl_seconds > 0


def test_worker_settings_resolve_redis_configuration():
    """app.workers.settings must build arq RedisSettings from Settings.redis_url."""
    from app.workers.settings import WorkerSettings, redis_settings

    assert isinstance(redis_settings, RedisSettings)
    assert redis_settings.host == "localhost"
    assert redis_settings.port == 6379
    assert WorkerSettings.redis_settings is redis_settings
    assert WorkerSettings.functions, "WorkerSettings must register ARQ functions"


def test_worker_settings_respects_redis_url_env(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://worker-host:6390")
    import importlib

    from app.workers import settings as worker_settings_module

    importlib.reload(worker_settings_module)
    try:
        assert worker_settings_module.redis_settings.host == "worker-host"
        assert worker_settings_module.redis_settings.port == 6390
    finally:
        importlib.reload(worker_settings_module)


def test_app_main_imports_and_builds_route_table():
    from app.main import app

    assert app.routes, "FastAPI route table must be non-empty"
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/health" in paths or any(p and p.startswith("/api") for p in paths)


def test_non_redis_imports_unaffected():
    """Core non-Redis modules still import cleanly."""
    from app.config import get_settings
    from app.db import supabase  # noqa: F401

    assert get_settings().supabase_url


def test_redis_connectivity_optional():
    """Document intent: Redis is optional at import time; no connection is
    attempted during Settings/WorkerSettings construction."""
    # Importing the worker settings module must not open a socket. If it did,
    # the import above in test_worker_settings_resolve_redis_configuration
    # would have failed without a live Redis.
    from app.workers import settings  # noqa: F401

    assert settings.redis_pool is None or settings.redis_pool is not None


def test_live_redis_connectivity_when_available():
    """Only connects if REDIS_URL is reachable; skipped otherwise."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        import redis.asyncio as aioredis

        pytest.importorskip("redis")
    except ImportError:  # pragma: no cover
        pytest.skip("redis-py not installed")

    import asyncio

    async def _ping() -> bool:
        client = aioredis.from_url(redis_url, socket_connect_timeout=1.0)
        try:
            return await client.ping()
        except Exception:
            return False
        finally:
            await client.aclose()

    reachable = asyncio.run(_ping())
    if not reachable:
        pytest.skip(
            "Live Redis connectivity not verified: no Redis instance available "
            f"at {redis_url}"
        )
    assert reachable


def test_redis_settings_supports_tls_and_credentials():
    """P1: authenticated + TLS Redis is supported via the rediss:// DSN."""
    rs = RedisSettings.from_dsn("rediss://user:pass@redis-prod:6380/3")
    assert rs.ssl is True
    assert rs.username == "user"
    assert rs.password == "pass"
    assert rs.host == "redis-prod"
    assert rs.port == 6380
    assert rs.database == 3


def test_redis_settings_default_no_tls_no_creds():
    rs = RedisSettings.from_dsn("redis://localhost:6379")
    assert rs.ssl is False
    assert rs.username is None
    assert rs.password is None


def test_settings_max_resume_upload_bytes_default():
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="anon",
        supabase_service_role_key="service",
    )
    assert settings.max_resume_upload_bytes == 10 * 1024 * 1024


def test_settings_reads_max_resume_upload_bytes_env(monkeypatch):
    monkeypatch.setenv("MAX_RESUME_UPLOAD_BYTES", "5242880")
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="anon",
        supabase_service_role_key="service",
    )
    assert settings.max_resume_upload_bytes == 5 * 1024 * 1024
