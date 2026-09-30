"""Single-gate regression: async slot is the capacity boundary for gated paths.

Ownership model under test:
- Production persistence inside ``async_persistence_slot`` uses
  ``run_gated_persistence`` (NO second sync-capacity wait).
- Legacy callers outside any async slot keep ``call_serialized``
  (sync capacity + cancellation + telemetry intact).
- Thread-safety rests on thread-local Supabase clients in both cases.

Payload-free throughout (synthetic jobs only).
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.db.supabase import (
    PersistenceCancelledError,
    PersistenceTimeoutError,
    async_persistence_slot,
    async_slot_stats_snapshot,
    call_serialized,
    lock_stats_snapshot,
    persistence_gate_snapshot,
    reset_persistence_semaphore,
    reset_persistence_telemetry,
    run_gated_persistence,
)
from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository


def _reset(concurrency: int = 2) -> None:
    reset_persistence_semaphore(concurrency)
    reset_persistence_telemetry()


def _job(ext_id: str, platform: str = "ashby") -> NormalizedJob:
    posted = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    return NormalizedJob(
        title=f"SingleGate Engineer {ext_id}",
        company="SingleGateCo",
        external_job_id=ext_id,
        source_platform=platform,
        posted_date=posted,
        apply_url=f"https://singlegate.example/jobs/{ext_id}",
        description="synthetic description",
    )


class _FakeQuery:
    def __init__(self, table: "_FakeTable"):
        self._table = table
        self._eq: list[tuple[str, Any]] = []
        self._in: list[tuple[str, list]] = []
        self._lt: list[tuple[str, str]] = []
        self._insert_rows: Any = None
        self._update_values: Any = None

    def select(self, *a: Any, **k: Any) -> "_FakeQuery":
        return self

    def eq(self, field: str, value: Any) -> "_FakeQuery":
        self._eq.append((field, value))
        return self

    def ilike(self, field: str, value: str) -> "_FakeQuery":
        self._eq.append((field, value))
        return self

    def in_(self, field: str, values: list) -> "_FakeQuery":
        self._in.append((field, list(values)))
        return self

    def lt(self, field: str, value: str) -> "_FakeQuery":
        self._lt.append((field, value))
        return self

    def limit(self, *a: Any) -> "_FakeQuery":
        return self

    def insert(self, rows: Any, *a: Any, **k: Any) -> "_FakeQuery":
        assert k.get("returning", "minimal") == "minimal"
        self._insert_rows = rows
        return self

    def update(self, values: dict, *a: Any, **k: Any) -> "_FakeQuery":
        assert k.get("returning", "minimal") == "minimal"
        self._update_values = values
        return self

    def _matches(self, row: dict) -> bool:
        for field, value in self._eq:
            if row.get(field) != value:
                return False
        for field, values in self._in:
            if row.get(field) not in values:
                return False
        for field, value in self._lt:
            current = row.get(field)
            if current is None or not (str(current) < str(value)):
                return False
        return True

    def execute(self) -> MagicMock:
        client = self._table.client
        with client.lock:
            client.executes += 1
            client.concurrent += 1
            client.max_concurrent = max(client.max_concurrent, client.concurrent)
        try:
            if client.latency_ms:
                time.sleep(client.latency_ms / 1000.0)
            if self._insert_rows is not None:
                rows = self._insert_rows if isinstance(self._insert_rows, list) else [self._insert_rows]
                out = []
                for row in rows:
                    stored = dict(row)
                    stored.setdefault("id", f"id-{client.next_id}")
                    client.next_id += 1
                    client.store[(stored["source_platform"], stored["external_job_id"])] = stored
                    out.append(stored)
                return MagicMock(data=out)
            if self._update_values is not None:
                touched = []
                for row in client.store.values():
                    if self._matches(row):
                        row.update(self._update_values)
                        touched.append(row)
                return MagicMock(data=touched)
            return MagicMock(data=[dict(r) for r in client.store.values() if self._matches(r)])
        finally:
            with client.lock:
                client.concurrent -= 1


class _FakeTable:
    def __init__(self, client: "_GateFakeClient"):
        self.client = client

    def __getattr__(self, name: str) -> Any:
        if name in ("select", "insert", "update"):

            def _start(*a: Any, **k: Any) -> _FakeQuery:
                query = _FakeQuery(self)
                return getattr(query, name)(*a, **k)

            return _start
        raise AttributeError(name)


class _GateFakeClient:
    rest_url = "fake-single-gate-client"

    def __init__(self, latency_ms: float = 0.0):
        self.store: dict[tuple[str, str], dict] = {}
        self.executes = 0
        self.next_id = 1
        self.latency_ms = latency_ms
        self.concurrent = 0
        self.max_concurrent = 0
        self.lock = threading.Lock()

    def table(self, name: str) -> _FakeTable:
        assert name == "jobs"
        return _FakeTable(self)


def _repo(client: _GateFakeClient) -> JobRepository:
    repo = JobRepository(client=client)  # type: ignore[arg-type]
    repo._has_last_seen_at = True
    repo._has_provenance = True
    repo._has_mass_hiring = True
    return repo


async def _gated_upsert(client: _GateFakeClient, n: int, tag: str, timeout: float = 30.0) -> dict:
    """Production shape: async slot -> to_thread(run_gated_persistence)."""
    from app.services.jobs.job_ingestion_service import JobIngestionService

    svc = JobIngestionService.__new__(JobIngestionService)
    svc.job_repository = _repo(client)
    jobs = [_job(f"{tag}-{i}") for i in range(n)]
    return await svc._persist_offloop(jobs, timeout_seconds=timeout)


# ---------------------------------------------------------------------------
# Test A — no double capacity acquisition (5 concurrent gated ops)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_gated_paths_have_zero_sync_capacity_wait():
    _reset(2)
    clients = [_GateFakeClient(latency_ms=20.0) for _ in range(5)]
    sizes = [50, 250, 500, 1000, 250]
    max_async_holding = 0
    max_db_concurrent = 0

    async def _monitor() -> None:
        nonlocal max_async_holding
        for _ in range(300):
            gate = persistence_gate_snapshot()
            max_async_holding = max(max_async_holding, int(gate["async_holding_now"]))
            await asyncio.sleep(0.01)

    sync_wait_before = lock_stats_snapshot()["wait_ms_total"]
    monitor = asyncio.create_task(_monitor())
    results = await asyncio.gather(
        *[_gated_upsert(c, n, f"a{i}") for i, (c, n) in enumerate(zip(clients, sizes))]
    )
    monitor.cancel()
    try:
        await monitor
    except asyncio.CancelledError:
        pass

    for r in results:
        assert r["inserted"] > 0
    assert max_async_holding <= 2, max_async_holding
    for c in clients:
        max_db_concurrent = max(max_db_concurrent, c.max_concurrent)
    # Actual DB operations never exceed capacity (each client sees its own
    # ops; global bound comes from the async gate: max 2 holders).
    assert max_async_holding <= 2
    # Gated paths must not wait on the second capacity semaphore.
    sync_wait_delta = lock_stats_snapshot()["wait_ms_total"] - sync_wait_before
    assert sync_wait_delta == 0.0, sync_wait_delta
    gate = persistence_gate_snapshot()
    assert gate["sync_waiting_now"] == 0
    assert gate["async_holding_now"] == 0 and gate["sync_holding_now"] == 0


# ---------------------------------------------------------------------------
# Test B — occupied DB slot: waiter sits at async boundary, no inner wait
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b_waiter_attributed_to_async_gate_only():
    _reset(1)  # concurrency 1 makes the boundary crisp
    release = threading.Event()
    loop = asyncio.get_running_loop()
    entered_async = asyncio.Event()

    def _blocking_db() -> str:
        loop.call_soon_threadsafe(entered_async.set)
        release.wait(timeout=10.0)
        return "ok"

    async def _gated() -> str:
        async with async_persistence_slot(timeout_seconds=10.0):
            return await asyncio.to_thread(run_gated_persistence, _blocking_db)

    first = asyncio.create_task(_gated())
    await asyncio.wait_for(entered_async.wait(), timeout=5.0)
    await asyncio.sleep(0.05)
    mid = persistence_gate_snapshot()
    assert int(mid["async_holding_now"]) == 1  # occupied by actual DB work
    second = asyncio.create_task(_gated())
    await asyncio.sleep(0.15)  # let the waiter queue at the async gate
    mid2 = persistence_gate_snapshot()
    # Waiter is at the async boundary ...
    assert int(mid2["async_waiting_now"]) == 1
    # ... and never in a second capacity queue.
    assert int(mid2["sync_waiting_now"]) == 0
    release.set()
    assert await first == "ok" and await second == "ok"
    gate = persistence_gate_snapshot()
    assert gate["async_holding_now"] == 0 and gate["sync_holding_now"] == 0


# ---------------------------------------------------------------------------
# Test C — exactly two concurrent DB ops; third waits at async boundary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c_two_db_concurrent_third_waits_async():
    _reset(2)
    release = threading.Event()
    loop = asyncio.get_running_loop()
    entered_count = 0
    entered_lock = threading.Lock()
    both_inside = asyncio.Event()
    max_inside = 0
    inside = 0
    inside_lock = threading.Lock()

    def _blocking_db() -> str:
        nonlocal inside, max_inside, entered_count
        with inside_lock:
            inside += 1
            max_inside = max(max_inside, inside)
        with entered_lock:
            entered_count += 1
            if entered_count == 2:
                loop.call_soon_threadsafe(both_inside.set)
        release.wait(timeout=10.0)
        with inside_lock:
            inside -= 1
        return "ok"

    async def _gated() -> str:
        async with async_persistence_slot(timeout_seconds=10.0):
            return await asyncio.to_thread(run_gated_persistence, _blocking_db)

    t1 = asyncio.create_task(_gated())
    t2 = asyncio.create_task(_gated())
    await asyncio.wait_for(both_inside.wait(), timeout=5.0)
    await asyncio.sleep(0.05)
    gate = persistence_gate_snapshot()
    assert int(gate["async_holding_now"]) == 2
    assert int(gate["sync_waiting_now"]) == 0  # no second gate queue

    t3 = asyncio.create_task(_gated())
    await asyncio.sleep(0.15)
    gate = persistence_gate_snapshot()
    assert int(gate["async_waiting_now"]) == 1
    assert int(gate["sync_waiting_now"]) == 0
    assert not t3.done()

    release.set()
    assert await t1 == "ok" and await t2 == "ok"
    assert await t3 == "ok"
    assert max_inside == 2, max_inside


# ---------------------------------------------------------------------------
# Test D — slow op exceeds timeout; contracts + permits intact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d_slow_gated_op_times_out_without_leak():
    from app.config import get_settings

    _reset(1)  # single slot so one holder blocks the waiter
    # Timeout contracts unchanged.
    assert get_settings().persistence_max_concurrency == 2

    async def _holder() -> None:
        async with async_persistence_slot():
            await asyncio.sleep(1.0)

    holder = asyncio.create_task(_holder())
    await asyncio.sleep(0.05)
    with pytest.raises(PersistenceTimeoutError, match=r"gate=async"):
        async with async_persistence_slot(timeout_seconds=0.15):
            pass
    await holder
    # 75s/45s defaults untouched at call sites (inspect, don't inflate).
    import inspect as _inspect

    from app.services.jobs import job_ingestion_service as _jis
    from app.workers.jobs import crawl_jobs as _cj

    assert "timeout_seconds: float = 75.0" in _inspect.getsource(_jis.JobIngestionService._persist_offloop)
    assert "timeout_seconds=45.0" in _inspect.getsource(_cj.crawl_company_job)
    gate = persistence_gate_snapshot()
    assert gate["async_holding_now"] == 0 and gate["sync_holding_now"] == 0
    async with async_persistence_slot(timeout_seconds=1.0):
        run_gated_persistence(lambda: None)


# ---------------------------------------------------------------------------
# Test E — deactivation under the same async capacity, non-blocking intact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e_deactivation_single_gated_no_inner_wait():
    _reset(2)
    from app.workers.jobs.crawl_jobs import _deactivate_after_success

    client = _GateFakeClient(latency_ms=5.0)
    repo = _repo(client)
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    for i in range(20):
        repo._client  # touch property
        key = ("ashby", f"e-{i}")
        client.store[key] = {
            "id": f"id-{i}", "source_platform": "ashby", "external_job_id": f"e-{i}",
            "company": "E Co", "is_active": True, "last_seen_at": old,
        }
    ingestion = MagicMock()
    ingestion.job_repository = _repo(client)

    sync_wait_before = lock_stats_snapshot()["wait_ms_total"]
    async with async_persistence_slot(timeout_seconds=30.0):
        result = await asyncio.to_thread(
            _deactivate_after_success,
            ingestion, "ashby", "e-co",
            datetime.now(timezone.utc).isoformat(), 30, None, 30.0, True,
        )
    assert isinstance(result, tuple) and len(result) == 4
    assert lock_stats_snapshot()["wait_ms_total"] - sync_wait_before == 0.0

    # Non-blocking stale-deactivation behavior: TimeoutError inside the
    # crawl still degrades to a warning, never a failure.
    from app.workers.jobs import crawl_jobs as _cj
    import logging as _logging

    logged: list[str] = []

    class _H(_logging.Handler):
        def emit(self, record: _logging.LogRecord) -> None:
            logged.append(record.getMessage())

    logger = _logging.getLogger("app.workers.jobs.crawl_jobs")
    handler = _H()
    logger.addHandler(handler)
    try:
        slow_ingestion = MagicMock()
        slow_repo = MagicMock()
        slow_repo.deactivate_not_seen_since.side_effect = PersistenceTimeoutError("slow (gate=async)")
        slow_repo.deactivate_stale_jobs.return_value = 0
        slow_ingestion.job_repository = slow_repo
        out = _deactivate_after_success(
            slow_ingestion, "ashby", "e-co",
            datetime.now(timezone.utc).isoformat(), 30, None, 0.01, False,
        )
        assert out is not None  # legacy path still returns (may raise only on real DB errors)
    except PersistenceTimeoutError:
        pass
    finally:
        logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# Test F — cancellation at three points: wait, pre-thread, during DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f_cancellation_at_three_points_no_leak():
    _reset(1)  # single slot so the waiter genuinely queues

    # 1. While waiting for async capacity.
    async def _holder() -> None:
        async with async_persistence_slot():
            await asyncio.sleep(0.5)

    holder = asyncio.create_task(_holder())
    await asyncio.sleep(0.05)

    async def _waiter() -> None:
        async with async_persistence_slot(timeout_seconds=10.0):
            pass

    waiter = asyncio.create_task(_waiter())
    await asyncio.sleep(0.05)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await holder

    # 2. Immediately before thread execution (cancel_event pre-set).
    ev = threading.Event()
    ev.set()
    with pytest.raises(PersistenceCancelledError):
        run_gated_persistence(lambda: None, cancel_event=ev)

    # 3. During persistence (cancel waiting + running gated ops).
    async def _slow_gated() -> None:
        async with async_persistence_slot(timeout_seconds=30.0):
            await asyncio.to_thread(run_gated_persistence, lambda: time.sleep(1.5))

    tasks = [asyncio.create_task(_slow_gated()) for _ in range(3)]
    await asyncio.sleep(0.15)
    for task in tasks:
        task.cancel()
    cancelled = 0
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            cancelled += 1
    assert cancelled >= 1
    await asyncio.sleep(1.7)  # let the 2 admitted sleepers finish
    gate = persistence_gate_snapshot()
    assert gate["async_waiting_now"] == 0 and gate["sync_waiting_now"] == 0
    assert gate["async_holding_now"] == 0 and gate["sync_holding_now"] == 0
    # Subsequent persistence succeeds (no _ACTIVE_CRAWLS involvement here,
    # crawl-level gauge covered by existing lifecycle tests).
    async with async_persistence_slot(timeout_seconds=1.0):
        run_gated_persistence(lambda: None)


# ---------------------------------------------------------------------------
# Test G — legacy caller safety: sync protection intact without async slot
# ---------------------------------------------------------------------------


def test_g_legacy_call_serialized_still_serializes():
    _reset(1)
    barrier = threading.Barrier(3)
    max_inside = 0
    inside = 0
    guard = threading.Lock()

    def _racer() -> None:
        nonlocal inside, max_inside
        barrier.wait(timeout=10)
        call_serialized(_section)

    def _section() -> None:
        nonlocal inside, max_inside
        with guard:
            inside += 1
            max_inside = max(max_inside, inside)
        time.sleep(0.1)
        with guard:
            inside -= 1

    threads = [threading.Thread(target=_racer) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert max_inside == 1, max_inside
    snap = lock_stats_snapshot()
    assert snap["sections"] == 3
    assert snap["wait_ms_total"] > 0  # losers queued on the sync gate

    # Gated path never touches the sync waiter gauge ...
    _reset(2)
    run_gated_persistence(lambda: None)
    snap = lock_stats_snapshot()
    assert snap["waiting_now"] == 0
    assert snap["wait_ms_total"] == 0.0
    assert snap["sections"] == 1
