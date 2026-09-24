"""Supabase client factory.

Provides a service-role client (bypasses RLS) for ingestion/repository work
and an RLS-authenticated client for user-scoped queries.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Any, Callable

from supabase import Client, ClientOptions, create_client

from app.config import get_settings

# Serializes synchronous use of the process-global service client across OS
# threads. The client multiplexes requests over shared HTTP/2 connections
# whose state machine is not safe for concurrent multi-threaded use, and
# postgrest does not retry transport errors (RemoteProtocolError). Executor
# threads (asyncio.to_thread crawl persistence) must funnel through
# call_serialized; asyncio primitives must NOT be used here (no running loop
# in worker threads). ponytail: process-wide for crawl persistence; split
# per-table/domain only if lock contention ever shows in duration_ms logs.
_SYNC_CLIENT_LOCK = threading.Lock()


def call_serialized(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Run a sync Supabase-client call with cross-thread mutual exclusion."""
    with _SYNC_CLIENT_LOCK:
        return fn(*args, **kwargs)


@lru_cache
def get_service_client() -> Client:
    """Return a service-role Supabase client (bypasses RLS)."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def get_authenticated_client(jwt: str) -> Client:
    """Return an RLS-authenticated Supabase client for a user JWT."""
    settings = get_settings()
    options = ClientOptions(
        headers={"Authorization": f"Bearer {jwt}"},
    )
    return create_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        options,
    )