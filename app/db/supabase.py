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

# Thread-local storage for service-role clients.
# Each OS thread gets its own isolated Client instance with its own HTTP/2
# connection pool, completely preventing cross-thread connection state
# corruption and httpx.RemoteProtocolError.
_THREAD_LOCAL = threading.local()

# Bounded persistence concurrency (semaphore).
# Replaces the single process-global mutex with a bounded semaphore
# (PERSISTENCE_MAX_CONCURRENCY, default 2). Each thread uses its own
# thread-local Supabase client so HTTP/2 transport state is never shared,
# while the semaphore bounds total database connection usage against Supabase.
_PERSISTENCE_SEMAPHORE: Optional[threading.BoundedSemaphore] = None
_SEMAPHORE_GUARD = threading.Lock()


def get_persistence_semaphore() -> threading.BoundedSemaphore:
    """Return the bounded persistence semaphore (initialized once)."""
    global _PERSISTENCE_SEMAPHORE
    if _PERSISTENCE_SEMAPHORE is None:
        with _SEMAPHORE_GUARD:
            if _PERSISTENCE_SEMAPHORE is None:
                try:
                    concurrency = max(1, get_settings().persistence_max_concurrency)
                except Exception:
                    concurrency = 2
                _PERSISTENCE_SEMAPHORE = threading.BoundedSemaphore(concurrency)
    return _PERSISTENCE_SEMAPHORE


def reset_persistence_semaphore(concurrency: Optional[int] = None) -> None:
    """Reset the persistence semaphore (for tests)."""
    global _PERSISTENCE_SEMAPHORE
    with _SEMAPHORE_GUARD:
        if concurrency is None:
            try:
                concurrency = max(1, get_settings().persistence_max_concurrency)
            except Exception:
                concurrency = 2
        _PERSISTENCE_SEMAPHORE = threading.BoundedSemaphore(concurrency)


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
    "holding_now": 0.0,  # threads currently executing (gauge)
}


def call_serialized(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Run a sync Supabase-client call with bounded cross-thread concurrency."""
    sem = get_persistence_semaphore()
    with _STATS_GUARD:
        _LOCK_STATS["waiting_now"] += 1
    queued_at = time.monotonic()
    with sem:
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


def get_service_client() -> Client:
    """Return a thread-local service-role Supabase client (bypasses RLS).

    Each thread maintains its own isolated Client instance with its own HTTP/2
    connection pool, completely eliminating cross-thread connection state
    corruption and httpx.RemoteProtocolError.
    """
    client = getattr(_THREAD_LOCAL, "service_client", None)
    if client is None:
        settings = get_settings()
        client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        _THREAD_LOCAL.service_client = client
    return client


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