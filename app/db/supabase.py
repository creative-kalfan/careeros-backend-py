"""Supabase client factory.

Provides a service-role client (bypasses RLS) for ingestion/repository work
and an RLS-authenticated client for user-scoped queries.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def get_service_client() -> Client:
    """Return a service-role Supabase client (bypasses RLS)."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def get_authenticated_client(jwt: str) -> Client:
    """Return an RLS-authenticated Supabase client for a user JWT."""
    settings = get_settings()
    return create_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        headers={"Authorization": f"Bearer {jwt}"},
    )