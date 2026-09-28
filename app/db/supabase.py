"""Supabase client factory.

Provides a service-role client (bypasses RLS) for ingestion/repository work
and an RLS-authenticated client for user-scoped queries.
"""

from __future__ import annotations

import threading
import time
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

# Lightweight lock-contention telemetry (production throughput diagnosis).
# Updated under _STATS_GUARD; reads via lock_stats_snapshot(). Overhead is a
# few monotonic() calls + integer ops per serialized section — negligible
# next to a Supabase round trip. Never logs payloads, only durations/counts.
_STATS_GUARD = threading.Lock()
_LOCK_STATS: dict[str, float] = {
    "sections": 0.0,  # total call_serialized executions
    "wait_ms_total": 0.0,  # time queued waiting for the lock
    "hold_ms_total": 0.0,  # time holding the lock (the serialized work)
    "wait_ms_max": 0.0,
    "hold_ms_max": 0.0,
    "waiting_now": 0.0,  # threads currently queued (gauge)
    "holding_now": 0.0,  # 0 or 1 (gauge)
}


def call_serialized(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Run a sync Supabase-client call with cross-thread mutual exclusion."""
    with _STATS_GUARD:
        _LOCK_STATS["waiting_now"] += 1
    queued_at = time.monotonic()
    with _SYNC_CLIENT_LOCK:
        wait_ms = (time.monotonic() - queued_at) * 1000.0
        with _STATS_GUARD:
            _LOCK_STATS["waiting_now"] -= 1
            _LOCK_STATS["holding_now"] += 1
        held_at = time.monotonic()
        try:
            return fn(*args, **kwargs)
        finally:
            hold_ms = (time.monotonic() - held_at) * 1000.0
            with _STATS_GUARD:
                _LOCK_STATS["holding_now"] -= 1
                _LOCK_STATS["sections"] += 1
                _LOCK_STATS["wait_ms_total"] += wait_ms
                _LOCK_STATS["hold_ms_total"] += hold_ms
                if wait_ms > _LOCK_STATS["wait_ms_max"]:
                    _LOCK_STATS["wait_ms_max"] = wait_ms
                if hold_ms > _LOCK_STATS["hold_ms_max"]:
                    _LOCK_STATS["hold_ms_max"] = hold_ms


def lock_stats_snapshot() -> dict[str, float]:
    """Return a copy of the serialization-lock contention counters."""
    with _STATS_GUARD:
        snap = dict(_LOCK_STATS)
    sections = snap["sections"] or 1.0
    snap["wait_ms_avg"] = snap["wait_ms_total"] / sections
    snap["hold_ms_avg"] = snap["hold_ms_total"] / sections
    return snap


def reset_lock_stats() -> None:
    """Zero the lock-contention counters (tests only)."""
    with _STATS_GUARD:
        for key in _LOCK_STATS:
            _LOCK_STATS[key] = 0.0


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