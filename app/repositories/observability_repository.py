"""Repository for crawl runs and job transition events observability."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from app.db.supabase import get_service_client

logger = logging.getLogger(__name__)

# Probe cache for table existence: probe_key -> bool
_PROBE_CACHE_OBSERVABILITY: dict[str, bool] = {}


class ObservabilityRepository:
    """Manages crawl_runs and job_events persistence with probe-cache degradation."""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = get_service_client()
        return self._client

    @classmethod
    def _probe_key(cls, client: Any) -> str:
        url = getattr(client, "supabase_url", None) or getattr(client, "_url", None)
        return str(url) if url else "default"

    def is_available(self) -> bool:
        """Check if crawl_runs table exists in Supabase."""
        client = self._get_client()
        key = self._probe_key(client)
        cached = _PROBE_CACHE_OBSERVABILITY.get(key)
        if cached is None:
            try:
                client.table("crawl_runs").select("id").limit(1).execute()
                cached = True
            except Exception:
                cached = False
            _PROBE_CACHE_OBSERVABILITY[key] = cached
        return cached

    def record_crawl_run(
        self,
        *,
        source: str,
        slug: str,
        started_at: datetime | str,
        finished_at: datetime | str,
        status: str,
        discovered: int = 0,
        inserted: int = 0,
        updated: int = 0,
        unchanged: int = 0,
        deactivated: int = 0,
        fetch_ms: int = 0,
        persist_wait_ms: int = 0,
        persist_hold_ms: int = 0,
        target_id: Optional[str] = None,
        error_type: Optional[str] = None,
        anomaly_reason: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Optional[str]:
        """Record a single crawl run. Returns the crawl_run_id if saved."""
        if not self.is_available():
            return None

        actual_run_id = run_id or str(uuid4())
        started_iso = started_at.isoformat() if isinstance(started_at, datetime) else str(started_at)
        finished_iso = finished_at.isoformat() if isinstance(finished_at, datetime) else str(finished_at)

        payload = {
            "id": actual_run_id,
            "source": source,
            "slug": slug,
            "started_at": started_iso,
            "finished_at": finished_iso,
            "status": status,
            "discovered": discovered,
            "inserted": inserted,
            "updated": updated,
            "unchanged": unchanged,
            "deactivated": deactivated,
            "fetch_ms": fetch_ms,
            "persist_wait_ms": persist_wait_ms,
            "persist_hold_ms": persist_hold_ms,
            "target_id": target_id,
            "error_type": error_type,
            "anomaly_reason": anomaly_reason,
        }

        try:
            self._get_client().table("crawl_runs").insert(payload, returning="minimal").execute()
            return actual_run_id
        except Exception as exc:
            logger.warning("Failed to insert crawl_runs row (non-blocking): %s", exc)
            return None

    def get_crawl_observability_summary(self, hours: int = 24, last_n_runs: int = 10) -> dict[str, Any]:
        """Fetch telemetry for /api/admin/crawl-status."""
        if not self.is_available():
            return {
                "available": False,
                "anomalies_24h": [],
                "last_runs_by_source": {},
                "jobs_per_day_by_source": {},
                "median_timing_ms": {"fetch_ms": 0, "persist_ms": 0},
            }

        client = self._get_client()
        now = datetime.now(timezone.utc)
        since_iso = (now - timedelta(hours=hours)).isoformat()

        # 1. Anomalies in past 24h
        anomalies: list[dict[str, Any]] = []
        try:
            res = (
                client.table("crawl_runs")
                .select("id, source, slug, started_at, status, discovered, anomaly_reason")
                .in_("status", ["anomaly", "suspicious_empty"])
                .gte("started_at", since_iso)
                .order("started_at", desc=True)
                .limit(50)
                .execute()
            )
            anomalies = res.data or []
        except Exception as exc:
            logger.warning("Failed to query crawl anomalies: %s", exc)

        # 2. Last N runs per source
        last_runs_by_source: dict[str, list[dict[str, Any]]] = {}
        try:
            res = (
                client.table("crawl_runs")
                .select("id, source, slug, started_at, finished_at, status, discovered, inserted, updated, unchanged, deactivated, fetch_ms, persist_wait_ms, persist_hold_ms")
                .order("started_at", desc=True)
                .limit(100)
                .execute()
            )
            for row in (res.data or []):
                src = row.get("source") or "unknown"
                runs = last_runs_by_source.setdefault(src, [])
                if len(runs) < last_n_runs:
                    runs.append(row)
        except Exception as exc:
            logger.warning("Failed to query last runs by source: %s", exc)

        # 3. Jobs per day by source (past 7 days)
        jobs_per_day_by_source: dict[str, dict[str, int]] = {}
        seven_days_ago = (now - timedelta(days=7)).isoformat()
        try:
            res = (
                client.table("crawl_runs")
                .select("source, started_at, inserted, updated")
                .gte("started_at", seven_days_ago)
                .execute()
            )
            for row in (res.data or []):
                src = row.get("source") or "unknown"
                started = row.get("started_at", "")[:10]  # YYYY-MM-DD
                total_jobs = int(row.get("inserted", 0)) + int(row.get("updated", 0))
                day_map = jobs_per_day_by_source.setdefault(src, {})
                day_map[started] = day_map.get(started, 0) + total_jobs
        except Exception as exc:
            logger.warning("Failed to query jobs per day: %s", exc)

        # 4. Median timings (fetch_ms and persist_wait_ms + persist_hold_ms)
        fetch_times: list[int] = []
        persist_times: list[int] = []
        try:
            res = (
                client.table("crawl_runs")
                .select("fetch_ms, persist_wait_ms, persist_hold_ms")
                .gte("started_at", since_iso)
                .limit(500)
                .execute()
            )
            for row in (res.data or []):
                fetch_times.append(int(row.get("fetch_ms") or 0))
                persist_times.append(int(row.get("persist_wait_ms") or 0) + int(row.get("persist_hold_ms") or 0))
        except Exception as exc:
            logger.warning("Failed to calculate median timings: %s", exc)

        def _median(arr: list[int]) -> int:
            if not arr:
                return 0
            s = sorted(arr)
            mid = len(s) // 2
            return s[mid] if len(s) % 2 != 0 else (s[mid - 1] + s[mid]) // 2

        return {
            "available": True,
            "anomalies_24h": anomalies,
            "last_runs_by_source": last_runs_by_source,
            "jobs_per_day_by_source": jobs_per_day_by_source,
            "median_timing_ms": {
                "fetch_ms": _median(fetch_times),
                "persist_ms": _median(persist_times),
            },
        }

    def prune_old_observability_data(self, retention_days: int = 90, batch_size: int = 500) -> dict[str, int]:
        """Prune crawl_runs and job_events older than retention_days. Bounded batches."""
        if not self.is_available():
            return {"pruned_events": 0, "pruned_runs": 0}

        client = self._get_client()
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        pruned_events = 0
        pruned_runs = 0

        # 1. Delete old job_events in bounded batch
        try:
            # Query IDs first for bounded deletion
            old_events_res = (
                client.table("job_events")
                .select("id")
                .lt("occurred_at", cutoff_iso)
                .limit(batch_size)
                .execute()
            )
            event_ids = [r["id"] for r in (old_events_res.data or []) if r.get("id")]
            if event_ids:
                client.table("job_events").delete().in_("id", event_ids).execute()
                pruned_events = len(event_ids)
        except Exception as exc:
            logger.warning("Failed to prune job_events: %s", exc)

        # 2. Delete old crawl_runs in bounded batch
        try:
            old_runs_res = (
                client.table("crawl_runs")
                .select("id")
                .lt("started_at", cutoff_iso)
                .limit(batch_size)
                .execute()
            )
            run_ids = [r["id"] for r in (old_runs_res.data or []) if r.get("id")]
            if run_ids:
                client.table("crawl_runs").delete().in_("id", run_ids).execute()
                pruned_runs = len(run_ids)
        except Exception as exc:
            logger.warning("Failed to prune crawl_runs: %s", exc)

        return {"pruned_events": pruned_events, "pruned_runs": pruned_runs}
