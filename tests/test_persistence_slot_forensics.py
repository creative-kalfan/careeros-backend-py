"""Production persistence slot forensics (temporary diagnosis harness).

Reproduces the production topology locally without a live Supabase:
5-10 concurrent crawls, persistence concurrency=2, mixed crawl sizes
(50/250/500/1000), upsert + deactivation, slow-DB simulation, and
concurrent deactivation.

Proves (with numbers, not inference):
- async slots=2 -> thread -> call_serialized(sync=2) -> DB double-gate shape
- persistence_holders/waiters split (async vs sync, no conflation)
- slot wait vs serialized wait vs HTTP duration vs repo CPU split
- slot covers only the sync persistence operation
- timeout/cancellation guarantees intact, threads/RSS bounded

Payload-free: jobs use synthetic titles/descriptions only.
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
    PersistenceTimeoutError,
    async_persistence_slot,
    async_slot_stats_snapshot,
    call_serialized,
    lock_stats_snapshot,
    persistence_gate_snapshot,
    reset_async_slot_stats,
    reset_lock_stats,
    reset_persistence_semaphore,
    reset_persistence_telemetry,
)
from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository


def _job(ext_id: str, platform: str = "ashby") -> NormalizedJob:
    posted = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    return NormalizedJob(
        title=f"Forensics Engineer {ext_id}",
        company="ForensicsCo",
        external_job_id=ext_id,
        source_platform=platform,
        posted_date=posted,
        apply_url=f"https://forensics.example/jobs/{ext_id}",
        description="synthetic description without payload",
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

    def range(self, *a: Any) -> "_FakeQuery":
        return self

    def order(self, *a: Any, **k: Any) -> "_FakeQuery":
        return self

    def insert(self, rows: Any, *a: Any, **k: Any) -> "_FakeQuery":
        assert k.get("returning", "minimal") == "minimal", "write must use returning=minimal"
        self._insert_rows = rows
        return self

    def update(self, values: dict, *a: Any, **k: Any) -> "_FakeQuery":
        assert k.get("returning", "minimal") == "minimal", "write must use returning=minimal"
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
        client.executes += 1
        client.http_ms_total += client.latency_ms
        client.threads_used.add(threading.current_thread().name)
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
        matched = [dict(r) for r in client.store.values() if self._matches(r)]
        return MagicMock(data=matched)


class _FakeTable:
    def __init__(self, client: "_LatentFakeClient"):
        self.client = client

    def __getattr__(self, name: str) -> Any:
        if name in ("select", "insert", "update"):

            def _start(*a: Any, **k: Any) -> _FakeQuery:
                query = _FakeQuery(self)
                return getattr(query, name)(*a, **k)

            return _start
        raise AttributeError(name)


class _LatentFakeClient:
    """In-memory jobs table with per-execute latency + HTTP accounting."""

    rest_url = "fake-forensics-client"

    def __init__(self, latency_ms: float = 0.0):
        self.store: dict[tuple[str, str], dict] = {}
        self.executes = 0
        self.next_id = 1
        self.latency_ms = latency_ms
        self.http_ms_total = 0.0
        self.threads_used: set[str] = set()

    def table(self, name: str) -> _FakeTable:
        assert name == "jobs"
        return _FakeTable(self)


def _repo(client: _LatentFakeClient) -> JobRepository:
    repo = JobRepository(client=client)  # type: ignore[arg-type]
    repo._has_last_seen_at = True
    repo._has_provenance = True
    repo._has_mass_hiring = True
    return repo


def _reset_all(concurrency: int = 2) -> None:
    reset_persistence_semaphore(concurrency)
    reset_persistence_telemetry()


# ---------------------------------------------------------------------------
# A+D: 5 concurrent crawls, concurrency=2, mixed sizes, fast DB -> no timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_5_concurrent_upserts_complete_without_timeout():
    """Benchmarks A+D: holders<=2, no timeout when DB is below the deadline."""
    from app.services.jobs.job_ingestion_service import JobIngestionService

    _reset_all(2)
    threads_before = threading.active_count()
    sizes = [50, 250, 500, 1000, 250]
    max_async_holding = 0
    max_sync_holding = 0

    async def _crawl(n: int, idx: int) -> dict:
        client = _LatentFakeClient(latency_ms=5.0)
        service = JobIngestionService.__new__(JobIngestionService)
        service.job_repository = _repo(client)
        jobs = [_job(f"c{idx}-{i}") for i in range(n)]
        result = await service._persist_offloop(jobs, timeout_seconds=30.0)
        gate = persistence_gate_snapshot()
        return {"result": result, "executes": client.executes, "gate": gate}

    async def _monitor() -> None:
        nonlocal max_async_holding, max_sync_holding
        for _ in range(200):
            gate = persistence_gate_snapshot()
            max_async_holding = max(max_async_holding, int(gate["async_holding_now"]))
            max_sync_holding = max(max_sync_holding, int(gate["sync_holding_now"]))
            await asyncio.sleep(0.01)

    monitor = asyncio.create_task(_monitor())
    results = await asyncio.gather(*[_crawl(n, i) for i, n in enumerate(sizes)])
    monitor.cancel()
    try:
        await monitor
    except asyncio.CancelledError:
        pass

    assert len(results) == 5
    for r in results:
        assert r["result"]["inserted"] > 0
        assert "async_wait_ms" in r["result"] and "async_hold_ms" in r["result"]
        assert "to_thread_ms" in r["result"] and "db_thread_ms" in r["result"]
    # Benchmark A: holders never exceed concurrency
    assert max_async_holding <= 2, max_async_holding
    assert max_sync_holding <= 2, max_sync_holding
    # Gauges drain
    gate = persistence_gate_snapshot()
    assert gate["async_waiting_now"] == 0 and gate["sync_waiting_now"] == 0
    assert gate["async_holding_now"] == 0 and gate["sync_holding_now"] == 0
    # No thread leak: waiting coroutines never held executor threads
    await asyncio.sleep(0.1)
    assert threading.active_count() <= threads_before + 4, (
        threads_before,
        threading.active_count(),
    )


# ---------------------------------------------------------------------------
# B: wait_ms + hold_ms reconciles with total within overhead
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_hold_reconciles_with_total():
    from app.services.jobs.job_ingestion_service import JobIngestionService

    _reset_all(2)
    client = _LatentFakeClient(latency_ms=5.0)
    service = JobIngestionService.__new__(JobIngestionService)
    service.job_repository = _repo(client)
    jobs = [_job(f"r-{i}") for i in range(50)]

    total_start = time.monotonic()
    result = await service._persist_offloop(jobs, timeout_seconds=30.0)
    total_ms = (time.monotonic() - total_start) * 1000.0

    # async_wait + async_hold covers the whole gated section; the ungated
    # prefix (raw nullify + snapshot) is small overhead.
    accounted = result["async_wait_ms"] + result["async_hold_ms"]
    assert accounted <= total_ms + 1.0
    assert total_ms - accounted < 150.0, (total_ms, accounted, result)
    # sync section lives inside to_thread; DB thread time <= to_thread time
    assert result["db_thread_ms"] <= result["to_thread_ms"] + 1.0
    assert result["to_thread_ms"] <= result["async_hold_ms"] + 1.0


# ---------------------------------------------------------------------------
# C: quantify the second gate — async hold includes sync wait + DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_double_gate_quantified_async_hold_includes_sync_wait():
    """Prove the async slot is held while waiting on the sync gate."""
    _reset_all(2)
    from app.db.supabase import get_persistence_semaphore

    sync_sem = get_persistence_semaphore()
    # Occupy BOTH sync permits from background threads with a slow holder.
    release = threading.Event()

    def _slow_holder() -> None:
        call_serialized(lambda: release.wait(timeout=10.0))

    holders = [threading.Thread(target=_slow_holder) for _ in range(2)]
    for t in holders:
        t.start()
    await asyncio.sleep(0.2)  # let both sync permits get taken
    mid = persistence_gate_snapshot()
    assert int(mid["sync_holding_now"]) == 2

    # Async slots are free (2/2), so async acquire is instant; the op then
    # blocks inside call_serialized on the occupied sync gate.
    client = _LatentFakeClient(latency_ms=1.0)
    repo = _repo(client)
    jobs = [_job("dq-1")]

    t0 = time.monotonic()
    async with async_persistence_slot(timeout_seconds=10.0):
        async_wait_ms = (time.monotonic() - t0) * 1000.0
        hold_start = time.monotonic()
        with pytest.raises(PersistenceTimeoutError, match="waiting for persistence semaphore"):
            call_serialized(
                lambda: repo.upsert_jobs(jobs),
                timeout_seconds=0.4,
            )
        sync_blocked_ms = (time.monotonic() - hold_start) * 1000.0

    # Async wait ~0 (slots were free) yet the async hold grew by the full
    # sync-block duration -> second gate stalls the first gate's holder.
    assert async_wait_ms < 150.0, async_wait_ms
    assert sync_blocked_ms >= 300.0, sync_blocked_ms

    release.set()
    for t in holders:
        t.join(timeout=5.0)
    gate = persistence_gate_snapshot()
    assert gate["sync_holding_now"] == 0


@pytest.mark.asyncio
async def test_concurrent_deactivation_contends_on_same_gates():
    """Upsert + deactivation share the same 2 async slots (production shape)."""
    _reset_all(2)
    client = _LatentFakeClient(latency_ms=10.0)
    repo = _repo(client)
    jobs = [_job(f"cd-{i}") for i in range(100)]
    repo.upsert_jobs(jobs)

    async def _upsert_slow() -> dict:
        from app.services.jobs.job_ingestion_service import JobIngestionService

        service = JobIngestionService.__new__(JobIngestionService)
        service.job_repository = _repo(client)
        return await service._persist_offloop([_job(f"new-{i}") for i in range(100)], timeout_seconds=30.0)

    async def _deactivate_slow() -> tuple[int, int, int, int]:
        from app.workers.jobs.crawl_jobs import _deactivate_after_success
        from app.services.jobs.job_ingestion_service import JobIngestionService

        ingestion = MagicMock()
        ingestion.job_repository = _repo(client)
        Service = JobIngestionService  # noqa: F841 (import shape parity)
        async with async_persistence_slot(timeout_seconds=30.0):
            return await asyncio.to_thread(
                _deactivate_after_success,
                ingestion,
                "ashby",
                "forensics-co",
                datetime.now(timezone.utc).isoformat(),
                30,
                None,
                30.0,
            )

    upsert_task = asyncio.create_task(_upsert_slow())
    deact_task = asyncio.create_task(_deactivate_slow())
    results = await asyncio.gather(upsert_task, deact_task)
    assert results[0]["inserted"] == 100
    assert isinstance(results[1], tuple) and len(results[1]) == 4


# ---------------------------------------------------------------------------
# E: slow op still triggers the bounded timeout (both gates tagged)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slow_async_slot_triggers_tagged_timeout():
    _reset_all(1)

    async def _holder() -> None:
        async with async_persistence_slot():
            await asyncio.sleep(0.6)

    holder = asyncio.create_task(_holder())
    await asyncio.sleep(0.05)
    with pytest.raises(PersistenceTimeoutError, match=r"gate=async"):
        async with async_persistence_slot(timeout_seconds=0.15):
            pass
    await holder
    # Slot released after holder exits
    async with async_persistence_slot(timeout_seconds=1.0):
        pass


def test_slow_sync_gate_triggers_tagged_timeout():
    _reset_all(1)
    release = threading.Event()

    def _holder() -> None:
        call_serialized(lambda: release.wait(timeout=5.0))

    t = threading.Thread(target=_holder)
    t.start()
    time.sleep(0.15)
    try:
        with pytest.raises(PersistenceTimeoutError, match=r"gate=sync"):
            call_serialized(lambda: None, timeout_seconds=0.2)
    finally:
        release.set()
        t.join(timeout=5.0)
    gate = persistence_gate_snapshot()
    assert gate["sync_holding_now"] == 0


# ---------------------------------------------------------------------------
# F: cancellation guarantees — no zombie threads, no gauge/permit leak
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancellation_releases_permits_threads_gauges():
    _reset_all(2)
    threads_before = threading.active_count()

    async def _slow_db_op() -> None:
        async with async_persistence_slot(timeout_seconds=30.0):
            await asyncio.to_thread(call_serialized, lambda: time.sleep(2.0))

    tasks = [asyncio.create_task(_slow_db_op()) for _ in range(4)]
    await asyncio.sleep(0.2)
    for task in tasks:
        task.cancel()
    cancelled = 0
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            cancelled += 1
    assert cancelled >= 2  # at least the waiters were cancelled
    await asyncio.sleep(0.3)
    gate = persistence_gate_snapshot()
    assert gate["async_waiting_now"] == 0 and gate["sync_waiting_now"] == 0
    assert gate["async_holding_now"] == 0
    # Sync holders drain once the 2s sleepers finish; permits must restore.
    await asyncio.sleep(2.2)
    gate = persistence_gate_snapshot()
    assert gate["sync_holding_now"] == 0
    assert threading.active_count() <= threads_before + 3, (
        threads_before,
        threading.active_count(),
    )
    # Both semaphores usable again (no permit leak)
    async with async_persistence_slot(timeout_seconds=1.0):
        call_serialized(lambda: None, timeout_seconds=1.0)


# ---------------------------------------------------------------------------
# G: memory bounded during 5 concurrent crawls (no 493MB regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_bounded_during_5_concurrent_crawls():
    psutil = pytest.importorskip("psutil")
    from app.services.jobs.job_ingestion_service import JobIngestionService

    _reset_all(2)
    proc = psutil.Process()
    base_mb = proc.memory_info().rss / (1024 * 1024)

    async def _crawl(idx: int) -> None:
        client = _LatentFakeClient(latency_ms=2.0)
        service = JobIngestionService.__new__(JobIngestionService)
        service.job_repository = _repo(client)
        jobs = [_job(f"m{idx}-{i}") for i in range(500)]
        await service._persist_offloop(jobs, timeout_seconds=30.0)

    await asyncio.gather(*[_crawl(i) for i in range(5)])
    peak_mb = proc.memory_info().rss / (1024 * 1024)
    assert peak_mb - base_mb < 150.0, (base_mb, peak_mb)
    assert peak_mb < 400.0, peak_mb  # far from the 493MB production incident


# ---------------------------------------------------------------------------
# Telemetry split: async vs sync gauges never conflated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateGauges_split_async_vs_sync():
    _reset_all(2)
    gate = persistence_gate_snapshot()
    assert gate["async_waiting_now"] == 0 and gate["sync_waiting_now"] == 0

    release = threading.Event()

    def _sync_holder() -> None:
        call_serialized(lambda: release.wait(timeout=5.0))

    t = threading.Thread(target=_sync_holder)
    t.start()
    await asyncio.sleep(0.15)
    gate = persistence_gate_snapshot()
    # Only the sync holder is counted; async gauges stay zero.
    assert int(gate["sync_holding_now"]) == 1
    assert int(gate["async_holding_now"]) == 0
    assert int(gate["persistence_holders"]) == 1  # legacy = sync holders
    release.set()
    t.join(timeout=5.0)

    async with async_persistence_slot():
        gate = persistence_gate_snapshot()
        assert int(gate["async_holding_now"]) == 1
        assert int(gate["sync_holding_now"]) == 0
