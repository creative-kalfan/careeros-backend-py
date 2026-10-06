"""Crawl throughput: bulk persistence equivalence + bottleneck instrumentation.

Proves the N+1 collapse fix without a live Supabase: an in-memory fake
PostgREST client implements real filter/insert/update semantics (including
23505 conflict races), and every scenario asserts identical counters AND
identical final table state to the specified contract.

Also covers: lock-contention telemetry, per-phase crawl timing, the ARQ
cancellation path, and the extended persistence log fields.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from postgrest.exceptions import APIError

from app.db.supabase import (
    call_serialized,
    lock_stats_snapshot,
    reset_lock_stats,
)
from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository

DUPLICATE_KEY_ERROR = APIError(
    {"message": "duplicate key value violates unique constraint", "code": "23505"}
)


def _job(ext_id: str, platform: str = "ashby", title: str = "Engineer",
         posted_days_ago: Optional[int] = 3, posted_date: Optional[str] = None, **extra: Any) -> NormalizedJob:
    posted = posted_date
    if posted is None and posted_days_ago is not None:
        posted = (datetime.now(timezone.utc) - timedelta(days=posted_days_ago)).isoformat()
    return NormalizedJob(
        title=title, company="Co", external_job_id=ext_id,
        source_platform=platform, posted_date=posted,
        apply_url=f"https://co.example/jobs/{ext_id}", **extra,
    )


_VALID_JOBS_COLUMNS = set(NormalizedJob._DB_COLUMNS.default) | {
    "id", "created_at", "updated_at", "last_seen_at", "first_seen_at",
    "last_crawled_at", "source_history",
}


class _FakeQuery:
    """Chainable in-memory PostgREST table with real filter/write semantics."""

    def __init__(self, table: "_FakeTable"):
        self._table = table
        self._eq: list[tuple[str, Any]] = []
        self._ilike: list[tuple[str, str]] = []
        self._in: list[tuple[str, list]] = []
        self._lt: list[tuple[str, str]] = []
        self._insert_rows: Any = None
        self._update_values: Any = None

    # -- builder --
    def select(self, *a: Any, **k: Any) -> "_FakeQuery":
        if a and isinstance(a[0], str) and a[0].strip() and a[0].strip() != "*":
            for col in a[0].split(","):
                c = col.strip()
                if c and c not in _VALID_JOBS_COLUMNS:
                    raise APIError({"message": f"column jobs.{c} does not exist", "code": "42703"})
        return self

    def eq(self, field: str, value: Any) -> "_FakeQuery":
        self._eq.append((field, value))
        return self

    def ilike(self, field: str, value: str) -> "_FakeQuery":
        self._ilike.append((field, value))
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
        self._insert_rows = rows
        return self

    def update(self, values: dict, *a: Any, **k: Any) -> "_FakeQuery":
        self._update_values = values
        return self

    # -- execution --
    def _matches(self, row: dict) -> bool:
        for field, value in self._eq:
            if row.get(field) != value:
                return False
        for field, value in self._ilike:
            current = row.get(field)
            if current is None or str(current).lower() != str(value).lower():
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
        if client.fail_next_bulk and self._in and self._update_values is not None:
            client.fail_next_bulk = False
            raise APIError({"message": "bulk write failed", "code": "500"})
        if self._insert_rows is not None:
            rows = self._insert_rows if isinstance(self._insert_rows, list) else [self._insert_rows]
            if client.race_hook is not None:
                client.race_hook(rows)
            for row in rows:
                key = (row.get("source_platform"), row.get("external_job_id"))
                if key in client.store:
                    raise DUPLICATE_KEY_ERROR
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
        matched = [r for r in client.store.values() if self._matches(r)]
        return MagicMock(data=[dict(r) for r in matched])


class _FakeTable:
    def __init__(self, client: "_FakeClient"):
        self.client = client

    def __getattr__(self, name: str) -> Any:
        if name in ("select", "insert", "update"):
            def _start(*a: Any, **k: Any) -> _FakeQuery:
                query = _FakeQuery(self)
                return getattr(query, name)(*a, **k)

            return _start
        raise AttributeError(name)


class _FakeClient:
    """In-memory jobs table; counts every execute() as one DB request."""

    rest_url = "fake-throughput-client"

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], dict] = {}
        self.executes = 0
        self.next_id = 1
        self.race_hook: Any = None
        self.fail_next_bulk = False

    def table(self, name: str) -> _FakeTable:
        assert name == "jobs"
        return _FakeTable(self)


def _repo(client: _FakeClient) -> JobRepository:
    repo = JobRepository(client=client)  # type: ignore[arg-type]
    # Preset column flags (the established test pattern): no probe SELECTs,
    # so execute counts measure exactly the upsert/deactivation I/O shape.
    repo._has_last_seen_at = True
    repo._has_provenance = True
    repo._has_mass_hiring = True
    return repo


def _seed(client: _FakeClient, rows: list[dict]) -> None:
    for row in rows:
        stored = dict(row)
        stored.setdefault("id", f"id-{client.next_id}")
        client.next_id += 1
        client.store[(stored["source_platform"], stored["external_job_id"])] = stored


# ---------------------------------------------------------------------------
# Bulk upsert equivalence
# ---------------------------------------------------------------------------


def test_bulk_all_new_matches_contract_and_collapses_requests():
    client = _FakeClient()
    repo = _repo(client)
    jobs = [_job(f"n-{i}") for i in range(100)]
    result = repo.upsert_jobs(jobs)
    assert result == {"discovered": 100, "inserted": 100, "updated": 0,
                      "unchanged": 0, "deduplicated": 0, "skipped": 0}
    assert len(client.store) == 100
    sample = client.store[("ashby", "n-0")]
    assert sample["last_seen_at"] and sample["first_seen_at"]
    # Old shape needed 200 requests (SELECT + INSERT per job); bulk needs
    # one fetch chunk + one write chunk.
    assert client.executes == 2, client.executes
    assert repo.last_db_requests == 2


def test_bulk_all_unchanged_refreshes_last_seen_only():
    client = _FakeClient()
    now = datetime.now(timezone.utc)
    jobs = [_job(f"u-{i}") for i in range(10)]
    seed_rows = []
    for i, job in enumerate(jobs):
        row = job.to_db_row()
        row.update({"id": f"row-{i}", "last_seen_at": (now - timedelta(days=2)).isoformat(),
                    "is_active": True, "sentinel": "keep-me"})
        seed_rows.append(row)
    _seed(client, seed_rows)
    before = {k: dict(v) for k, v in client.store.items()}

    repo = _repo(client)
    result = repo.upsert_jobs(jobs)
    assert result["unchanged"] == 10 and result["inserted"] == 0 and result["updated"] == 0
    for key, stored in client.store.items():
        assert stored["sentinel"] == "keep-me"  # touch never rewrites content
        assert stored["last_seen_at"] > before[key]["last_seen_at"]
    # Old shape: 10 SELECTs + 10 touch UPDATEs = 20; bulk: 1 + 1.
    assert client.executes == 2, client.executes


def test_bulk_mixed_new_changed_unchanged_dupe_skipped():
    client = _FakeClient()
    keep_job = _job("keep", title="Same")
    keep_row = keep_job.to_db_row()
    keep_row.update({"id": "row-keep", "is_active": True,
                     "last_seen_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()})
    change_row = dict(keep_row, external_job_id="chg", id="row-chg", title="Old Title")
    _seed(client, [keep_row, change_row])

    repo = _repo(client)
    jobs = [
        keep_job,                            # unchanged -> touch
        _job("chg", title="New Title"),      # changed -> full update, same id
        _job("brand-new"),                   # insert
        _job("brand-new"),                   # in-batch dupe
        NormalizedJob(title="No Identity"),  # skipped
    ]
    result = repo.upsert_jobs(jobs)
    assert result == {"discovered": 5, "inserted": 1, "updated": 1,
                      "unchanged": 1, "deduplicated": 1, "skipped": 1}
    assert client.store[("ashby", "chg")]["id"] == "row-chg"
    assert client.store[("ashby", "chg")]["title"] == "New Title"
    assert len(client.store) == 3


def test_bulk_insert_race_falls_back_to_live_update():
    client = _FakeClient()
    repo = _repo(client)
    job = _job("racer")

    def _race(rows: list[dict]) -> None:
        # Another worker wins between our fetch and our write (with
        # different content, so the fallback takes the update path).
        winner = job.to_db_row()
        winner["id"] = "winner-id"
        winner["title"] = "Changed By Winner"
        client.store[("ashby", "racer")] = winner

    client.race_hook = _race
    result = repo.upsert_jobs([job])
    assert result["updated"] == 1 and result["inserted"] == 0
    assert client.store[("ashby", "racer")]["id"] == "winner-id"


def test_bulk_insert_race_without_winner_counts_deduplicated():
    client = _FakeClient()
    repo = _repo(client)

    class _RaceClient(_FakeClient):
        def table(self, name: str) -> _FakeTable:
            return _RaceTable(self)

    class _RaceTable(_FakeTable):
        def __getattr__(self, name: str) -> Any:
            if name == "insert":
                def _boom(*a: Any, **k: Any) -> Any:
                    raise DUPLICATE_KEY_ERROR

                return _boom
            return super().__getattr__(name)

    racing = _RaceClient()
    repo2 = _repo(racing)
    result = repo2.upsert_jobs([_job("ghost")])
    assert result["deduplicated"] == 1 and result["inserted"] == 0


def test_bulk_preserves_source_escalation_and_never_downgrades():
    client = _FakeClient()
    low = _job("esc")
    low_row = low.to_db_row()
    low_row.update({"id": "row-esc", "source_tier": 5, "source_provider": "adzuna",
                    "is_active": True,
                    "last_seen_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()})
    worse_row = dict(low_row, external_job_id="keep", id="row-keep",
                     source_tier=1, source_provider="greenhouse", title="Official Title")
    _seed(client, [low_row, worse_row])

    repo = _repo(client)
    official = _job("esc", title="Changed Title")
    official.source_tier = 1
    official.source_provider = "greenhouse"
    official.source_verified = True
    downgrade = _job("keep", title="Changed Title")
    downgrade.source_tier = 5
    downgrade.source_provider = "adzuna"
    result = repo.upsert_jobs([official, downgrade])
    assert result["updated"] == 2
    upgraded = client.store[("ashby", "esc")]
    assert upgraded["source_tier"] == 1
    assert upgraded["source_history"][-1]["source_tier"] == 5
    kept = client.store[("ashby", "keep")]
    assert kept["source_tier"] == 1  # better provenance kept
    assert kept["source_provider"] == "greenhouse"


def test_bulk_reactivates_fresh_reobservation():
    client = _FakeClient()
    job = _job("re", posted_days_ago=5)
    row = job.to_db_row()
    row.update({"id": "row-re", "is_active": False,
                "last_seen_at": (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()})
    _seed(client, [row])
    repo = _repo(client)
    result = repo.upsert_jobs([job])
    assert result["unchanged"] == 1
    stored = client.store[("ashby", "re")]
    assert stored["is_active"] is True


def test_bulk_unchanged_without_last_seen_column_issues_no_update():
    client = _FakeClient()
    job = _job("nl")
    row = job.to_db_row()
    row.update({"id": "row-nl", "is_active": True})
    _seed(client, [row])
    repo = _repo(client)
    repo._has_last_seen_at = False
    before_executes = client.executes
    # Same object for seed and upsert: wall-clock tick boundaries must not
    # decide content equality.
    result = repo.upsert_jobs([job])
    assert result["unchanged"] == 1
    # Only the existence fetch; no touch UPDATE (matches old behavior).
    assert client.executes == before_executes + 1


# ---------------------------------------------------------------------------
# Bulk deactivation equivalence
# ---------------------------------------------------------------------------


def test_bulk_not_seen_deactivation_same_rows_fewer_requests():
    client = _FakeClient()
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    _seed(client, [
        {"id": "s1", "source_platform": "ashby", "external_job_id": "a",
         "company": "Acme", "crawl_target_slug": "acme", "is_active": True, "last_seen_at": old},
        {"id": "s2", "source_platform": "ashby", "external_job_id": "b",
         "company": "Acme", "crawl_target_slug": "acme", "is_active": True, "last_seen_at": old},
        {"id": "s3", "source_platform": "ashby", "external_job_id": "c",
         "company": "Acme", "crawl_target_slug": "acme", "is_active": True, "last_seen_at": fresh},
        {"id": "s4", "source_platform": "greenhouse", "external_job_id": "d",
         "company": "Other", "crawl_target_slug": "other", "is_active": True, "last_seen_at": old},
    ])
    repo = _repo(client)
    count = repo.deactivate_not_seen_since("ashby", fresh, company="Acme", slug="acme")
    assert count == 2
    assert client.store[("ashby", "a")]["is_active"] is False
    assert client.store[("ashby", "b")]["is_active"] is False
    assert client.store[("ashby", "c")]["is_active"] is True
    assert client.store[("greenhouse", "d")]["is_active"] is True
    # Old shape: 1 SELECT + 2 UPDATEs; bulk: 1 SELECT + 1 UPDATE.
    assert client.executes == 2, client.executes


def test_bulk_stale_deactivation_uses_observation_freshness():
    client = _FakeClient()
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    seen_today = datetime.now(timezone.utc).isoformat()
    _seed(client, [
        {"id": "o1", "source_platform": "ashby", "external_job_id": "a",
         "company": "Acme", "crawl_target_slug": "acme", "is_active": True, "last_seen_at": old, "posted_at": old},
        {"id": "o2", "source_platform": "ashby", "external_job_id": "b",
         "company": "Acme", "crawl_target_slug": "acme", "is_active": True, "last_seen_at": seen_today, "posted_at": old},
        {"id": "o3", "source_platform": "ashby", "external_job_id": "c",
         "company": "Acme", "crawl_target_slug": "acme", "is_active": True},  # no usable date: never staleness-deleted
    ])
    repo = _repo(client)
    assert repo.deactivate_stale_jobs(source_platform="ashby", max_age_days=30, company="Acme", slug="acme") == 1
    assert client.store[("ashby", "a")]["is_active"] is False
    assert client.store[("ashby", "b")]["is_active"] is True
    assert client.store[("ashby", "c")]["is_active"] is True


def test_bulk_deactivation_chunk_failure_keeps_partial_progress():
    client = _FakeClient()
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    _seed(client, [
        {"id": f"s{i}", "source_platform": "ashby", "external_job_id": str(i),
         "company": "Acme", "crawl_target_slug": "acme", "is_active": True, "last_seen_at": old}
        for i in range(3)
    ])
    client.fail_next_bulk = True  # bulk chunk fails; per-row fallback must save progress
    repo = _repo(client)
    assert repo.deactivate_not_seen_since("ashby", fresh, company="Acme", slug="acme") == 3


# ---------------------------------------------------------------------------
# Lock telemetry
# ---------------------------------------------------------------------------


def test_lock_stats_record_wait_and_hold():
    reset_lock_stats()
    call_serialized(lambda: None)
    snap = lock_stats_snapshot()
    assert snap["sections"] == 1
    assert snap["waiting_now"] == 0 and snap["holding_now"] == 0
    assert snap["hold_ms_total"] >= 0 and snap["wait_ms_max"] >= 0
    assert "wait_ms_avg" in snap and "hold_ms_avg" in snap


def test_lock_serializes_threads_and_counts_waiters():
    import threading
    import time as _t

    reset_lock_stats()
    barrier = threading.Barrier(3)

    def _racer() -> None:
        barrier.wait(timeout=10)  # all three arrive together, then contend
        call_serialized(lambda: _t.sleep(0.2))

    threads = [threading.Thread(target=_racer) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    snap = lock_stats_snapshot()
    assert snap["sections"] == 3
    assert snap["wait_ms_total"] > 0  # losers queued behind the holder
    assert snap["waiting_now"] == 0 and snap["holding_now"] == 0


# ---------------------------------------------------------------------------
# Crawl-job phase timing, gauge, cancellation
# ---------------------------------------------------------------------------


def _patch_service(monkeypatch: Any, method: str, effect: Any) -> Any:
    from app.workers.jobs import crawl_jobs

    ingestion = MagicMock()
    ingestion.job_repository = MagicMock()
    ingestion.job_repository.deactivate_not_seen_since.return_value = 0
    ingestion.job_repository.deactivate_stale_jobs.return_value = 0
    if isinstance(effect, BaseException):
        setattr(ingestion, method, AsyncMock(side_effect=effect))
    else:
        setattr(ingestion, method, AsyncMock(return_value=effect))
    monkeypatch.setattr(crawl_jobs, "JobIngestionService", lambda *a, **k: ingestion)
    monkeypatch.setattr(crawl_jobs, "_record_crawl_status", AsyncMock())
    monkeypatch.setattr(crawl_jobs, "get_event_bus", MagicMock(), raising=False)
    return crawl_jobs


@pytest.mark.asyncio
async def test_crawl_logs_provider_phase_and_gauge(monkeypatch, caplog):
    from app.workers.jobs import crawl_jobs

    crawl_jobs_mod = _patch_service(
        monkeypatch, "ingest_ashby_jobs",
        {"discovered": 2, "inserted": 1, "updated": 0, "unchanged": 1,
         "deduplicated": 0, "skipped": 0},
    )
    with caplog.at_level(logging.INFO):
        result = await crawl_jobs_mod.crawl_company_job({"job_id": "t"}, "ashby", "openai")
    assert result["success"] is True
    text = caplog.text
    assert "phase=discover_normalize" in text
    assert "provider_ms=" in text
    assert "active_crawls=0" in text
    assert crawl_jobs_mod.active_crawl_count() == 0


@pytest.mark.asyncio
async def test_crawl_cancellation_records_state_and_reraises(monkeypatch):
    from app.workers.jobs import crawl_jobs

    crawl_jobs_mod = _patch_service(
        monkeypatch, "ingest_ashby_jobs", asyncio.CancelledError("ARQ timeout")
    )
    with pytest.raises(asyncio.CancelledError):
        await crawl_jobs_mod.crawl_company_job({"job_id": "t"}, "ashby", "openai")
    status_payload = crawl_jobs_mod._record_crawl_status.await_args.args[2]
    assert status_payload["status"] == "cancelled"
    assert crawl_jobs_mod.active_crawl_count() == 0


@pytest.mark.asyncio
async def test_persist_offloop_logs_throughput_fields(caplog):
    from app.services.jobs.job_ingestion_service import JobIngestionService

    def _ok_sync(jobs: list) -> dict:
        return {"discovered": len(jobs), "inserted": len(jobs), "updated": 0,
                "unchanged": 0, "deduplicated": 0, "skipped": 0}

    service = JobIngestionService.__new__(JobIngestionService)
    service.job_repository = MagicMock()
    service.job_repository.upsert_jobs.side_effect = _ok_sync
    service.job_repository.last_db_requests = 3

    reset_lock_stats()
    with caplog.at_level(logging.INFO, logger="app.services.jobs.job_ingestion_service"):
        await service._persist_offloop([NormalizedJob(title="T")])
    text = caplog.text
    for field in ("phase=upsert", "inserted=", "db_requests=", "lock_wait_ms=",
                  "lock_hold_ms=", "lock_waiting="):
        assert field in text, field


# ---------------------------------------------------------------------------
# Benchmarks: Datetime normalization & Bounded Database Requests
# ---------------------------------------------------------------------------


def test_bulk_unchanged_with_iso_z_vs_offset_normalizes_to_touch():
    """ISO Z vs +00:00 difference must normalize to touch, never triggering N+1 updates."""
    client = _FakeClient()
    jobs = []
    seed_rows = []
    for i in range(10):
        # API returns 'Z' format
        job = _job(f"z-{i}", posted_days_ago=None, posted_date="2026-09-10T16:54:37.622Z")
        jobs.append(job)
        row = job.to_db_row()
        # DB returned '+00:00' format
        row.update({
            "id": f"row-{i}",
            "posted_at": "2026-09-10T16:54:37.622+00:00",
            "last_seen_at": "2026-09-08T00:00:00+00:00",
            "is_active": True,
        })
        seed_rows.append(row)
    _seed(client, seed_rows)

    repo = _repo(client)
    result = repo.upsert_jobs(jobs)
    # Must be 10 unchanged (touch), NOT 10 updated
    assert result["unchanged"] == 10
    assert result["updated"] == 0
    assert result["inserted"] == 0
    # Must be exactly 2 requests (1 bulk SELECT + 1 bulk touch UPDATE), not 11 (1 + 10)
    assert client.executes == 2
    assert repo.last_db_requests == 2


@pytest.mark.parametrize(
    "size,expected_fetch,expected_write",
    [
        (10, 1, 1),
        (100, 1, 1),
        (500, 3, 3),
        (1000, 5, 5),
    ],
)
def test_board_size_db_requests_bounded_new_jobs(size, expected_fetch, expected_write):
    """Proves DB request count scales as O(ceil(N / chunk)), never O(N)."""
    client = _FakeClient()
    repo = _repo(client)
    jobs = [_job(f"job-{i}") for i in range(size)]
    result = repo.upsert_jobs(jobs)
    assert result["inserted"] == size
    assert client.executes == expected_fetch + expected_write
    assert repo.last_db_requests == expected_fetch + expected_write


@pytest.mark.parametrize(
    "size,expected_fetch,expected_touch",
    [
        (10, 1, 1),
        (100, 1, 1),
        (500, 3, 1),
        (1000, 5, 2),
    ],
)
def test_board_size_db_requests_bounded_recrawl(size, expected_fetch, expected_touch):
    """Recrawls of unchanged boards scale with O(ceil(N / 500)) for bulk touch."""
    client = _FakeClient()
    jobs = [_job(f"recrawl-{i}") for i in range(size)]
    seed_rows = []
    for i, j in enumerate(jobs):
        row = j.to_db_row()
        row.update({
            "id": f"row-{i}",
            "last_seen_at": "2026-09-01T00:00:00+00:00",
            "is_active": True,
        })
        seed_rows.append(row)
    _seed(client, seed_rows)

    repo = _repo(client)
    result = repo.upsert_jobs(jobs)
    assert result["unchanged"] == size
    assert result["updated"] == 0
    assert client.executes == expected_fetch + expected_touch


def test_deactivate_not_seen_since_scoped_to_company():
    """Deactivation scoped to company does not deactivate other companies on same platform."""
    client = _FakeClient()
    repo = _repo(client)

    # Seed 2 active jobs for OpenAI and 2 active jobs for Notion on Ashby
    openai_1 = {"id": "o1", "source_platform": "ashby", "external_job_id": "o1",
                "company": "OpenAI", "is_active": True, "last_seen_at": "2026-09-20T00:00:00+00:00"}
    openai_2 = {"id": "o2", "source_platform": "ashby", "external_job_id": "o2",
                "company": "OpenAI", "is_active": True, "last_seen_at": "2026-09-29T12:00:00+00:00"}
    notion_1 = {"id": "n1", "source_platform": "ashby", "external_job_id": "n1",
                "company": "Notion", "is_active": True, "last_seen_at": "2026-09-20T00:00:00+00:00"}
    notion_2 = {"id": "n2", "source_platform": "ashby", "external_job_id": "n2",
                "company": "Notion", "is_active": True, "last_seen_at": "2026-09-20T00:00:00+00:00"}
    _seed(client, [openai_1, openai_2, notion_1, notion_2])

    # Crawl of OpenAI runs at 2026-09-29T00:00:00
    deactivated = repo.deactivate_not_seen_since(
        source_platform="ashby",
        since_iso="2026-09-29T00:00:00+00:00",
        company="OpenAI",
    )
    # Only o1 should be deactivated (it was seen at 2026-09-20 < 2026-09-29).
    # Notion jobs (n1, n2) MUST NOT be deactivated!
    assert deactivated == 1
    assert client.store[("ashby", "o1")]["is_active"] is False
    assert client.store[("ashby", "o2")]["is_active"] is True
    assert client.store[("ashby", "n1")]["is_active"] is True
    assert client.store[("ashby", "n2")]["is_active"] is True


@pytest.mark.asyncio
async def test_scheduled_crawl_runner_staggers_enqueues():
    """Provider pass staggers enqueued jobs with _defer to prevent queue storms."""
    from app.services.jobs.scheduled_crawl_runner import ScheduledCrawlRunner

    runner = ScheduledCrawlRunner()
    enqueued: list[tuple[str, str, Optional[int]]] = []

    async def _mock_enqueue(source: str, slug: str, _defer: Optional[int] = None) -> None:
        enqueued.append((source, slug, _defer))

    runner._enqueue_crawl = _mock_enqueue
    # Run firecrawl pass (multiple targets)
    await runner.run_provider_pass("firecrawl")

    assert len(enqueued) > 1
    # First target has no defer (or 0)
    assert enqueued[0][2] is None
    # Subsequent targets have positive increasing defer delays
    for i in range(1, len(enqueued)):
        assert enqueued[i][2] is not None
        assert enqueued[i][2] > 0
        assert enqueued[i][2] > (enqueued[i-1][2] or 0)

def test_identity_lookup_projection_uses_only_valid_schema_columns():
    """Every column in _EXISTING_ROW_COLUMNS must exist in the canonical schema.

    Regression test for PostgREST 42703: jobs.salary does not exist in the
    canonical schema or PostgreSQL jobs table.
    """
    from app.repositories.job_repository import _EXISTING_ROW_COLUMNS, _CONTENT_FIELDS

    assert "salary" not in _CONTENT_FIELDS
    assert "salary" not in _EXISTING_ROW_COLUMNS.split(",")
    for col in _EXISTING_ROW_COLUMNS.split(","):
        assert col.strip() in _VALID_JOBS_COLUMNS, f"Nonexistent column in identity lookup: {col}"

    client = _FakeClient()
    repo = _repo(client)
    found = repo._find_many_by_identity("ashby", ["ext-1", "ext-2"])
    assert found == {}


def test_schema_mismatch_simulation_raises_42703_for_salary():
    """Simulate the production failure: querying jobs.salary must raise 42703."""
    client = _FakeClient()
    with pytest.raises(APIError) as exc_info:
        client.table("jobs").select("id,title,salary").execute()
    assert getattr(exc_info.value, "code", None) == "42703" or "42703" in str(exc_info.value)
    assert "jobs.salary" in str(exc_info.value)


def test_upsert_jobs_handles_salary_fields_and_schema_correctly():
    """Verify salary handling: model salary/salary_min/salary_max vs actual DB schema.

    - New job with salary metadata is inserted with salary_min/max in DB (no salary column).
    - Unchanged job is recognized as unchanged (touch only).
    - Changed salary range (salary_max) triggers full update.
    - Pure formatting change on model-only salary string does not trigger false UPDATE.
    """
    client = _FakeClient()
    repo = _repo(client)
    fixed_posted = "2026-09-01T00:00:00+00:00"

    job = _job(
        "sal-1",
        title="Backend Dev",
        posted_date=fixed_posted,
        salary="$100k - $120k",
        salary_currency="USD",
        salary_min=100000.0,
        salary_max=120000.0,
    )

    # 1. New job insert
    res1 = repo.upsert_jobs([job])
    assert res1["inserted"] == 1
    stored = client.store[("ashby", "sal-1")]
    assert stored["salary_min"] == 100000.0
    assert stored["salary_max"] == 120000.0
    assert "salary" not in stored

    # 2. Unchanged job recrawl -> touch only
    res2 = repo.upsert_jobs([job])
    assert res2["unchanged"] == 1 and res2["updated"] == 0

    # 3. Model-only salary string change without range change -> still unchanged
    job_str_change = _job(
        "sal-1",
        title="Backend Dev",
        posted_date=fixed_posted,
        salary="100,000 - 120,000 USD",
        salary_currency="USD",
        salary_min=100000.0,
        salary_max=120000.0,
    )
    res3 = repo.upsert_jobs([job_str_change])
    assert res3["unchanged"] == 1 and res3["updated"] == 0

    # 4. Actual range change (salary_max) -> full update
    job_range_change = _job(
        "sal-1",
        title="Backend Dev",
        posted_date=fixed_posted,
        salary="$100k - $140k",
        salary_currency="USD",
        salary_min=100000.0,
        salary_max=140000.0,
    )
    res4 = repo.upsert_jobs([job_range_change])
    assert res4["updated"] == 1
    assert client.store[("ashby", "sal-1")]["salary_max"] == 140000.0
