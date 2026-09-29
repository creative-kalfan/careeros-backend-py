"""Job repository: persistence and querying of jobs in Supabase.

Uses the service-role client so ingestion can upsert jobs regardless of RLS.
Deduplication identity is ``(source_platform, external_job_id)`` with a
database-level partial unique index (migration 013) backing the race-safe
SELECT-then-INSERT fallback in :meth:`upsert_jobs`.

Source provenance: rows carry ``source_tier`` / ``source_provider`` / etc.
(migration 016). When the same job is later discovered from a BETTER source
(e.g. a secondary listing is found on the company's official career page),
the existing canonical row is UPGRADED in place — never duplicated. Historical
provenance is preserved in ``source_history``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from postgrest.exceptions import APIError
from supabase import Client

from app.db.supabase import get_service_client
from app.models.job import NormalizedJob

logger = logging.getLogger(__name__)

# Fields compared to decide whether an existing row actually changed.
_CONTENT_FIELDS = (
    "title", "company", "location", "description", "url", "posted_at",
    "role_category", "application_deadline", "employment_type",
    "salary_min", "salary_max", "skills", "experience_level", "remote",
    "mass_hiring", "mass_hiring_status", "mass_hiring_details",
)

_MASS_HIRING_FIELDS = ("mass_hiring", "mass_hiring_status", "mass_hiring_details")

_DUPLICATE_KEY_CODE = "23505"

# Provenance columns written on insert/upgrade.
_PROVENANCE_FIELDS = (
    "source_tier", "source_provider", "canonical_url", "source_verified",
    "source_confidence", "company_website", "careers_url", "logo_url",
    "first_seen_at", "last_crawled_at", "source_history",
)

# Bulk I/O chunk sizes: bound per-request payload/URL length so no single
# PostgREST call grows with board size. 200 identities ≈ 4-6KB of query
# string; 200 full rows ≈ ~1-2MB worst case (large HTML descriptions) —
# safely under Supabase limits while collapsing ~2N round trips per batch
# to a handful. Deactivation IDs are tiny (UUIDs), hence the larger chunk.
_UPSERT_FETCH_CHUNK = 200
_UPSERT_WRITE_CHUNK = 200
_DEACTIVATE_ID_CHUNK = 500

# Projected columns for the bulk existence fetch. Strictly the fields the
# upsert decision reads (identity + _is_same_job content + provenance +
# lifecycle flags) — a fraction of select("*") payload per row.
_EXISTING_ROW_COLUMNS = ",".join(
    dict.fromkeys(
        (
            "id", "is_active", "source_history",
            "external_job_id", "source_platform",
            *_CONTENT_FIELDS, *_PROVENANCE_FIELDS,
        )
    )
)

# Module-level column-availability cache. Schema is stable for a process
# lifetime; per-instance None forced a ~1s SELECT on every request because
# get_job_relevance_service() constructs a new JobRepository each call.
# Tests that need a forced re-probe can clear these dicts.
_PROBE_CACHE_LAST_SEEN: dict[str, bool] = {}
_PROBE_CACHE_PROVENANCE: dict[str, bool] = {}
_PROBE_CACHE_MASS_HIRING: dict[str, bool] = {}


class JobRepository:
    """Data-access layer for the Supabase ``jobs`` table."""

    def __init__(self, client: Optional[Client] = None) -> None:
        self._custom_client = client
        # Column availability flags (instance-level; warm from module cache).
        self._has_last_seen_at: Optional[bool] = None
        self._has_provenance: Optional[bool] = None
        self._has_mass_hiring: Optional[bool] = None
        # Logical Supabase request count for the most recent write call
        # (upsert/deactivate). Repositories are per-crawl instances, so this
        # is thread-confined; surfaced for throughput observability without
        # changing any result-dict contract.
        self._db_requests = 0
        self.last_db_requests = 0

    @property
    def _client(self) -> Client:
        if self._custom_client is not None:
            return self._custom_client
        return get_service_client()

    @_client.setter
    def _client(self, value: Optional[Client]) -> None:
        self._custom_client = value

    # ------------------------------------------------------------------
    # Column probing
    # ------------------------------------------------------------------

    @staticmethod
    def _probe_key(client: Client) -> str:
        """Cache key per underlying Supabase URL (tests may inject clients)."""
        return str(getattr(client, "rest_url", "") or getattr(client, "url", "") or id(client))

    @classmethod
    def clear_probe_cache(cls) -> None:
        """Drop cached column probes (for tests that toggle schema)."""
        _PROBE_CACHE_LAST_SEEN.clear()
        _PROBE_CACHE_PROVENANCE.clear()
        _PROBE_CACHE_MASS_HIRING.clear()

    def _probe_has_last_seen_at(self) -> bool:
        """Check whether the ``last_seen_at`` column exists (migration 011)."""
        if self._has_last_seen_at is None:
            key = self._probe_key(self._client)
            cached = _PROBE_CACHE_LAST_SEEN.get(key)
            if cached is None:
                try:
                    self._client.table("jobs").select("last_seen_at").limit(1).execute()
                    cached = True
                except Exception:
                    cached = False
                _PROBE_CACHE_LAST_SEEN[key] = cached
            self._has_last_seen_at = cached
        return self._has_last_seen_at

    def _probe_has_provenance(self) -> bool:
        """Check whether provenance columns exist (migration 016)."""
        if self._has_provenance is None:
            key = self._probe_key(self._client)
            cached = _PROBE_CACHE_PROVENANCE.get(key)
            if cached is None:
                try:
                    self._client.table("jobs").select("source_tier").limit(1).execute()
                    cached = True
                except Exception:
                    cached = False
                _PROBE_CACHE_PROVENANCE[key] = cached
            self._has_provenance = cached
        return self._has_provenance

    def _probe_has_mass_hiring(self) -> bool:
        """Check whether mass_hiring columns exist (migration 021)."""
        if self._has_mass_hiring is None:
            key = self._probe_key(self._client)
            cached = _PROBE_CACHE_MASS_HIRING.get(key)
            if cached is None:
                try:
                    self._client.table("jobs").select("mass_hiring").limit(1).execute()
                    cached = True
                except Exception:
                    cached = False
                _PROBE_CACHE_MASS_HIRING[key] = cached
            self._has_mass_hiring = cached
        return self._has_mass_hiring

    def _get_candidate_select_columns(self) -> str:
        """Return projected columns for candidate universe queries to eliminate payload bloat."""
        base = (
            "id,title,company,location,description,url,posted_at,role_category,is_active,"
            "source_platform,external_job_id,remote,workplace_type,employment_type,"
            "salary_min,salary_max,experience_level,skills,"
            "source_tier,source_provider,canonical_url,source_verified,source_confidence"
        )
        if self._probe_has_last_seen_at():
            base += ",last_seen_at"
        if self._probe_has_mass_hiring():
            base += ",mass_hiring,mass_hiring_status,mass_hiring_details"
        return base

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_row(value: Any) -> Optional[dict[str, Any]]:
        """Normalize a lookup result to a single row dict (or None)."""
        if isinstance(value, list):
            return value[0] if value else None
        return value

    def _find_by_identity(
        self, external_job_id: str, source_platform: str
    ) -> Optional[dict[str, Any]]:
        """Find an existing job row by its (source_platform, external_job_id)."""
        result = (
            self._client.table("jobs")
            .select("*")
            .eq("external_job_id", external_job_id)
            .eq("source_platform", source_platform)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None

    @staticmethod
    def _normalize_val(field: str, val: Any) -> Any:
        """Normalize values for robust equality comparison."""
        if val is None or val == "":
            return None
        if field in ("posted_at", "application_deadline", "first_seen_at", "last_seen_at", "last_crawled_at"):
            if isinstance(val, str):
                try:
                    dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except Exception:
                    return val
            return val
        if field == "skills":
            if isinstance(val, list):
                return sorted(str(s).strip().lower() for s in val if s)
            return val
        if field in ("salary_min", "salary_max") and val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                return val
        if field in ("remote", "source_verified") and val is not None:
            return bool(val)
        return val

    @classmethod
    def _is_same_job(cls, existing: dict[str, Any], row: dict[str, Any]) -> bool:
        """True when the existing row content matches the new row content."""
        for field in _CONTENT_FIELDS:
            ex_val = cls._normalize_val(field, existing.get(field))
            row_val = cls._normalize_val(field, row.get(field))
            if ex_val != row_val:
                return False
        return True

    @staticmethod
    def _provenance_from_row(existing: dict[str, Any]) -> dict[str, Any]:
        """Extract provenance values from an existing DB row."""
        return {
            field: existing.get(field)
            for field in _PROVENANCE_FIELDS
            if existing.get(field) is not None
        }

    @staticmethod
    def _tier_of(values: dict[str, Any]) -> Optional[int]:
        tier = values.get("source_tier")
        try:
            return int(tier) if tier is not None else None
        except (TypeError, ValueError):
            return None

    def _apply_source_escalation(
        self, new_row: dict[str, Any], existing: Optional[dict[str, Any]]
    ) -> dict[str, Any]:
        """Merge source provenance, upgrading but never downgrading.

        - No existing row: provenance passes through as-is.
        - New tier better (lower) than existing: upgrade provenance and record
          the previous provenance in ``source_history``.
        - New tier worse or equal: keep the existing (better) provenance.
        """
        if not self._probe_has_provenance():
            return {k: v for k, v in new_row.items() if k not in _PROVENANCE_FIELDS}

        if not existing:
            return new_row

        existing_prov = self._provenance_from_row(existing)
        new_tier = self._tier_of(new_row)
        existing_tier = self._tier_of(existing_prov)

        if existing_tier is None:
            return {**new_row, **existing_prov}

        if new_tier is not None and new_tier < existing_tier:
            # Source upgrade: preserve the previous provenance historically.
            history = existing.get("source_history") or []
            new_row["source_history"] = [
                *history,
                {**existing_prov, "upgraded_at": datetime.now(timezone.utc).isoformat()},
            ]
            return new_row

        # Keep the better/existing provenance; strip new provenance fields.
        downgraded = {k: v for k, v in new_row.items() if k not in _PROVENANCE_FIELDS}
        return {**downgraded, **existing_prov}


    def _find_many_by_identity(
        self, source_platform: str, external_ids: list[str]
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Bulk existence fetch: {(external_job_id, source_platform): row}.

        One projected SELECT per chunk — the N individual
        :meth:`_find_by_identity` round trips collapsed. Returns exactly the
        rows the per-row lookups would (same predicate, same table); chunks
        keep the ``in_`` query string URL-safe. Lookup failures propagate,
        matching the per-row behavior (a failed crawl retries via ARQ).
        """
        found: dict[tuple[str, str], dict[str, Any]] = {}
        ids = [i for i in dict.fromkeys(external_ids) if i]
        for start in range(0, len(ids), _UPSERT_FETCH_CHUNK):
            chunk = ids[start:start + _UPSERT_FETCH_CHUNK]
            self._db_requests += 1
            result = (
                self._client.table("jobs")
                .select(_EXISTING_ROW_COLUMNS)
                .eq("source_platform", source_platform)
                .in_("external_job_id", chunk)
                .execute()
            )
            rows = result.data or []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and row.get("external_job_id"):
                    found[(row["external_job_id"], source_platform)] = row
        return found

    def _classify_row(
        self,
        key: tuple[str, str],
        row: dict[str, Any],
        existing: Optional[dict[str, Any]],
        now_iso: str,
        has_last_seen: bool,
    ) -> tuple[str, Any]:
        """Map one (row, existing) pair to a write action.

        Single implementation of the upsert decision semantics shared by the
        bulk path and the single-row race fallback. Actions:

        - ("insert", row)
        - ("touch", id) — same content: refresh ``last_seen_at`` only
        - ("reactivate", id) — same content + fresh re-observation of an
          inactive row: refresh ``last_seen_at`` and set active
        - ("update", id, row) — content changed: full-row update
        - ("noop", None) — same content with nothing to refresh
        """
        if existing is None:
            new_row = self._apply_source_escalation(row, None)
            if self._probe_has_provenance():
                new_row.setdefault("first_seen_at", now_iso)
            return ("insert", new_row)
        new_row = self._apply_source_escalation(row, existing)
        row_id = existing.get("id")
        if self._is_same_job(existing, new_row):
            # Nothing changed: refresh last_seen, and re-activate a
            # previously-deactivated row when the re-observed posting is
            # still fresh. Re-observation is positive evidence the job is
            # currently listed (e.g. after not-seen churn or a lapsed
            # crawl); the age staleness check in to_db_row still governs
            # whether it MAY be active, so old postings stay inactive.
            if existing.get("is_active") is False and new_row.get("is_active") is True:
                return ("reactivate", row_id)
            if has_last_seen:
                return ("touch", row_id)
            return ("noop", None)
        return ("update", row_id, new_row)

    def _upsert_single(
        self,
        key: tuple[str, str],
        row: dict[str, Any],
        now_iso: str,
        has_last_seen: bool,
    ) -> str:
        """Today's exact per-row write path (insert-race fallback only).

        Live-lookup, insert, 23505 re-lookup, update/touch — identical
        semantics to the pre-bulk implementation. Used only when a bulk
        insert chunk reports a duplicate-key race.
        """
        existing = self._coerce_row(self._find_by_identity(*key))
        action, *payload = self._classify_row(key, row, existing, now_iso, has_last_seen)
        if action == "insert":
            try:
                self._db_requests += 1
                self._client.table("jobs").insert(payload[0]).execute()
                return "inserted"
            except APIError as exc:
                args = str(getattr(exc, "args", ""))
                code = str(getattr(exc, "code", "") or "")
                if _DUPLICATE_KEY_CODE not in code and _DUPLICATE_KEY_CODE not in args:
                    raise
                # Lost the insert race: another worker created the row.
                winner = self._coerce_row(self._find_by_identity(*key))
                if not winner:
                    return "deduplicated"
                w_action, *w_payload = self._classify_row(
                    key, row, winner, now_iso, has_last_seen
                )
                return self._execute_single_action(w_action, w_payload, has_last_seen, now_iso)
        return self._execute_single_action(action, payload, has_last_seen, now_iso)

    def _execute_single_action(
        self,
        action: str,
        payload: list[Any],
        has_last_seen: bool,
        now_iso: str,
    ) -> str:
        """Execute one classified non-insert action; return the counter name."""
        if action == "touch":
            if has_last_seen:
                self._db_requests += 1
                self._client.table("jobs").update(
                    {"last_seen_at": now_iso}
                ).eq("id", payload[0]).execute()
            return "unchanged"
        if action == "reactivate":
            update: dict[str, Any] = {"is_active": True}
            if has_last_seen:
                update["last_seen_at"] = now_iso
            self._db_requests += 1
            self._client.table("jobs").update(update).eq("id", payload[0]).execute()
            return "unchanged"
        if action == "update":
            self._db_requests += 1
            self._client.table("jobs").update(payload[1]).eq(
                "id", payload[0]
            ).execute()
            return "updated"
        return "unchanged"

    def upsert_jobs(self, jobs: list[NormalizedJob]) -> dict[str, int]:
        """Upsert a batch of normalized jobs idempotently.

        Counters: discovered, inserted, updated, unchanged, deduplicated, skipped.

        Throughput shape (measured): one projected existence SELECT per
        platform chunk + one bulk INSERT per new-row chunk + one bulk touch
        UPDATE + per-row UPDATEs only for content-changed rows (rare on
        recrawl) — instead of 1 SELECT + 1 INSERT/UPDATE per job. Row
        decisions (identity, dedup, escalation, touch/reactivate, conflict
        fallback) are byte-for-byte the pre-bulk semantics via
        :meth:`_classify_row`.
        """
        inserted = 0
        updated = 0
        unchanged = 0
        deduplicated = 0
        skipped = 0
        self._db_requests = 0
        seen_keys: set[tuple[str, str]] = set()

        now_iso = datetime.now(timezone.utc).isoformat()
        has_last_seen = self._probe_has_last_seen_at()

        has_mass_hiring = self._probe_has_mass_hiring()

        # Phase 1: materialize rows (pure Python, no I/O).
        pending: list[tuple[tuple[str, str], dict[str, Any]]] = []
        for job in jobs:
            if not job.external_job_id or not job.source_platform:
                skipped += 1
                continue

            key = (job.external_job_id, job.source_platform)
            if key in seen_keys:
                deduplicated += 1
                continue
            seen_keys.add(key)

            row = job.to_db_row()
            if not has_mass_hiring:
                for f in _MASS_HIRING_FIELDS:
                    row.pop(f, None)
            if has_last_seen:
                row["last_seen_at"] = now_iso
            pending.append((key, row))

        # Phase 2: one bulk existence fetch per platform (chunked).
        by_platform: dict[str, list[str]] = {}
        for key, _row in pending:
            by_platform.setdefault(key[1], []).append(key[0])
        existing_map: dict[tuple[str, str], dict[str, Any]] = {}
        for platform, ids in by_platform.items():
            existing_map.update(self._find_many_by_identity(platform, ids))

        # Phase 3: classify every row with the single shared decision fn.
        to_insert: list[dict[str, Any]] = []
        insert_keys: list[tuple[str, str]] = []
        insert_rows: list[dict[str, Any]] = []
        touch_ids: list[str] = []
        reactivate_ids: list[str] = []
        full_updates: list[tuple[str, dict[str, Any]]] = []
        singles: list[tuple[tuple[str, str], dict[str, Any]]] = []
        for key, row in pending:
            action, *payload = self._classify_row(
                key, row, existing_map.get(key), now_iso, has_last_seen
            )
            if action == "insert":
                to_insert.append(payload[0])
                insert_keys.append(key)
                insert_rows.append(row)
            elif action == "touch":
                if payload[0] is None:
                    singles.append((key, row))
                else:
                    touch_ids.append(payload[0])
                    unchanged += 1
            elif action == "reactivate":
                if payload[0] is None:
                    singles.append((key, row))
                else:
                    reactivate_ids.append(payload[0])
                    unchanged += 1
            elif action == "update":
                if payload[0] is None:
                    singles.append((key, row))
                else:
                    full_updates.append((payload[0], payload[1]))
                    updated += 1
            else:  # noop: same content, nothing to refresh
                unchanged += 1

        # Phase 4a: bulk insert new rows (chunked); 23505 races fall back
        # to the exact per-row path for that chunk only.
        for start in range(0, len(to_insert), _UPSERT_WRITE_CHUNK):
            chunk = to_insert[start:start + _UPSERT_WRITE_CHUNK]
            chunk_keys = insert_keys[start:start + _UPSERT_WRITE_CHUNK]
            chunk_rows = insert_rows[start:start + _UPSERT_WRITE_CHUNK]
            try:
                self._db_requests += 1
                self._client.table("jobs").insert(chunk).execute()
                inserted += len(chunk)
            except APIError as exc:
                args = str(getattr(exc, "args", ""))
                code = str(getattr(exc, "code", "") or "")
                if _DUPLICATE_KEY_CODE not in code and _DUPLICATE_KEY_CODE not in args:
                    raise
                for key, row in zip(chunk_keys, chunk_rows):
                    outcome = self._upsert_single(key, row, now_iso, has_last_seen)
                    if outcome == "inserted":
                        inserted += 1
                    elif outcome == "updated":
                        updated += 1
                    elif outcome == "deduplicated":
                        deduplicated += 1
                    else:
                        unchanged += 1

        # Phase 4b: bulk touch (last_seen refresh) + bulk reactivate.
        if has_last_seen and touch_ids:
            for start in range(0, len(touch_ids), _DEACTIVATE_ID_CHUNK):
                chunk = touch_ids[start:start + _DEACTIVATE_ID_CHUNK]
                self._db_requests += 1
                self._client.table("jobs").update(
                    {"last_seen_at": now_iso}
                ).in_("id", chunk).execute()
        if reactivate_ids:
            payload: dict[str, Any] = {"is_active": True}
            if has_last_seen:
                payload["last_seen_at"] = now_iso
            for start in range(0, len(reactivate_ids), _DEACTIVATE_ID_CHUNK):
                chunk = reactivate_ids[start:start + _DEACTIVATE_ID_CHUNK]
                self._db_requests += 1
                self._client.table("jobs").update(payload).in_("id", chunk).execute()

        # Phase 4c: content-changed rows keep the exact per-row full update.
        for row_id, new_row in full_updates:
            self._db_requests += 1
            self._client.table("jobs").update(new_row).eq("id", row_id).execute()

        # Phase 4d: defensive singles (existing row without an id — the old
        # code would KeyError here; route through the live per-row path).
        for key, row in singles:
            outcome = self._upsert_single(key, row, now_iso, has_last_seen)
            if outcome == "inserted":
                inserted += 1
            elif outcome == "updated":
                updated += 1
            elif outcome == "deduplicated":
                deduplicated += 1
            else:
                unchanged += 1

        self.last_db_requests = self._db_requests
        return {
            "discovered": len(jobs),
            "inserted": inserted,
            "updated": updated,
            "unchanged": unchanged,
            "deduplicated": deduplicated,
            "skipped": skipped,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def deactivate_stale_jobs(
        self,
        source_platform: Optional[str] = None,
        max_age_days: int = 30,
        company: Optional[str] = None,
        careers_url: Optional[str] = None,
    ) -> int:
        """Deactivate active jobs from a source that are no longer fresh.

        NO LONGER SEEN -> INACTIVE (never deleted). Scoped to
        ``source_platform`` and optionally ``company``/``careers_url`` so one
        company can never deactivate or scan another company's jobs.
        """
        if not self._probe_has_last_seen_at():
            return 0

        self._db_requests = 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        query = (
            self._client.table("jobs")
            .select("id, posted_at, last_seen_at")
            .eq("is_active", True)
        )
        if source_platform:
            query = query.eq("source_platform", source_platform)
        if company:
            query = query.eq("company", company)
        if careers_url:
            query = query.eq("careers_url", careers_url)

        try:
            self._db_requests += 1
            result = query.execute()
        except APIError:
            logger.warning("deactivate_stale_jobs: query failed", exc_info=True)
            return 0

        def _parse_dt(value: Any) -> Optional[datetime]:
            if not value:
                return None
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                return None

        stale_ids: list[str] = []
        for row in result.data or []:
            # Observation freshness wins: a re-observed old posting is still
            # listed, so last_seen_at (not posted_at) decides staleness.
            observed = _parse_dt(row.get("last_seen_at")) or _parse_dt(row.get("posted_at"))
            if observed is not None and observed >= cutoff:
                continue
            if observed is None:
                continue  # no usable date: never delete-by-staleness
            if isinstance(row, dict) and row.get("id"):
                stale_ids.append(row["id"])
        count = self._bulk_set_inactive(stale_ids, what="deactivate_stale_jobs")
        self.last_db_requests = self._db_requests
        return count

    def _bulk_set_inactive(self, ids: list[str], what: str) -> int:
        """Set ``is_active=False`` for ids in bulk (chunked ``in_`` UPDATEs).

        Same rows, same values as the former per-row loop. Best-effort
        parity: a failed chunk falls back to per-row updates so one bad id
        never forfeits the rest of the chunk's progress.
        """
        count = 0
        for start in range(0, len(ids), _DEACTIVATE_ID_CHUNK):
            chunk = ids[start:start + _DEACTIVATE_ID_CHUNK]
            try:
                self._db_requests += 1
                self._client.table("jobs").update({"is_active": False}).in_(
                    "id", chunk
                ).execute()
                count += len(chunk)
            except APIError:
                for row_id in chunk:
                    try:
                        self._db_requests += 1
                        self._client.table("jobs").update({"is_active": False}).eq(
                            "id", row_id
                        ).execute()
                        count += 1
                    except APIError:
                        logger.warning("%s: update failed for %s", what, row_id)
        return count


    def deactivate_not_seen_since(
        self,
        source_platform: str,
        since_iso: str,
        careers_url: Optional[str] = None,
        company: Optional[str] = None,
    ) -> int:
        """Deactivate active jobs from a source NOT observed since ``since_iso``.

        Called only after a SUCCESSFUL crawl of ``source_platform``: any still
        active row whose ``last_seen_at`` predates the crawl start was not seen
        during the crawl and is therefore considered closed at the source.
        Rows are deactivated (never deleted).

        When ``company`` is provided (e.g. for single-board ATS crawls), the
        deactivation is strictly scoped to that company so crawls of one company
        never deactivate other companies on the same platform.

        When ``careers_url`` is provided (Firecrawl per-company crawls), the
        deactivation is additionally scoped to that careers URL so one
        company's successful crawl can never deactivate another company's
        jobs that share the same ``source_platform``.

        Returns the number of deactivated rows.
        """
        if not self._probe_has_last_seen_at():
            return 0

        self._db_requests = 0
        query = (
            self._client.table("jobs")
            .select("id")
            .eq("is_active", True)
            .eq("source_platform", source_platform)
            .lt("last_seen_at", since_iso)
        )
        if careers_url:
            query = query.eq("careers_url", careers_url)
        if company:
            query = query.eq("company", company)

        try:
            self._db_requests += 1
            result = query.execute()
        except APIError:
            logger.warning("deactivate_not_seen_since: query failed", exc_info=True)
            return 0

        ids = [
            row["id"] for row in (result.data or [])
            if isinstance(row, dict) and row.get("id")
        ]
        count = self._bulk_set_inactive(ids, what="deactivate_not_seen_since")
        if count:
            logger.info(
                "deactivate_not_seen_since: %d rows deactivated (source=%s company=%s since=%s careers_url=%s)",
                count, source_platform, company or "-", since_iso, careers_url or "-",
            )
        self.last_db_requests = self._db_requests
        return count

    def count_active(self) -> int:
        """Return the number of active jobs."""
        result = (
            self._client.table("jobs")
            .select("id", count="exact")
            .eq("is_active", True)
            .execute()
        )
        return result.count or 0

    def list_jobs(
        self,
        page: int = 1,
        page_size: int = 20,
        role: Optional[str] = None,
        location: Optional[str] = None,
        role_category: Optional[str] = None,
        company: Optional[str] = None,
        remote: Optional[bool] = None,
        employment_type: Optional[str] = None,
        experience: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return a page of active jobs plus the total count.

        Filters: role (title ilike), location (ilike), role_category (eq),
        company (ilike), remote (eq), employment_type (ilike),
        experience (eq). Sort: newest/oldest (posted_at), salary (salary_max).
        """
        offset = (page - 1) * page_size
        cols = self._get_candidate_select_columns()
        query = self._client.table("jobs").select(cols, count="exact").eq("is_active", True)

        if role:
            query = query.ilike("title", f"%{role}%")
        if location:
            loc_clean = location.strip()
            if loc_clean.lower() in ("bangalore", "bengaluru"):
                query = query.or_("location.ilike.%bangalore%,location.ilike.%bengaluru%")
            else:
                query = query.ilike("location", f"%{loc_clean}%")
        if role_category:
            query = query.eq("role_category", role_category)
        if company:
            query = query.ilike("company", f"%{company}%")
        if remote is True:
            query = query.ilike("location", "%remote%")
        elif remote is False:
            query = query.not_.ilike("location", "%remote%")
        if employment_type:
            query = query.ilike("employment_type", f"%{employment_type}%")
        if experience:
            query = query.eq("experience_level", experience)

        if sort == "newest":
            query = query.order("posted_at", desc=True)
        elif sort == "oldest":
            query = query.order("posted_at", desc=False)
        elif sort == "salary":
            query = query.order("salary_max", desc=True)
        else:
            query = query.order("created_at", desc=True)

        if page_size <= 1000:
            query = query.range(offset, offset + page_size - 1)
            result = query.execute()
            return (result.data or []), (result.count or 0)

        # PostgREST caps single queries at 1,000 rows.
        # When page_size > 1000, fetch in 1000-row chunks up to min(page_size, total_count).
        batch_res = query.range(offset, offset + 999).execute()
        total_count = batch_res.count or 0
        rows = list(batch_res.data or [])

        while len(rows) < min(page_size, total_count):
            start = offset + len(rows)
            end = min(offset + page_size, offset + len(rows) + 1000) - 1
            chunk_query = self._client.table("jobs").select(cols).eq("is_active", True)
            if role:
                chunk_query = chunk_query.ilike("title", f"%{role}%")
            if location:
                loc_clean = location.strip()
                if loc_clean.lower() in ("bangalore", "bengaluru"):
                    chunk_query = chunk_query.or_("location.ilike.%bangalore%,location.ilike.%bengaluru%")
                else:
                    chunk_query = chunk_query.ilike("location", f"%{loc_clean}%")
            if role_category:
                chunk_query = chunk_query.eq("role_category", role_category)
            if company:
                chunk_query = chunk_query.ilike("company", f"%{company}%")
            if remote is True:
                chunk_query = chunk_query.ilike("location", "%remote%")
            elif remote is False:
                chunk_query = chunk_query.not_.ilike("location", "%remote%")
            if employment_type:
                chunk_query = chunk_query.ilike("employment_type", f"%{employment_type}%")
            if experience:
                chunk_query = chunk_query.eq("experience_level", experience)

            if sort == "newest":
                chunk_query = chunk_query.order("posted_at", desc=True)
            elif sort == "oldest":
                chunk_query = chunk_query.order("posted_at", desc=False)
            elif sort == "salary":
                chunk_query = chunk_query.order("salary_max", desc=True)
            else:
                chunk_query = chunk_query.order("created_at", desc=True)

            try:
                chunk_res = chunk_query.range(start, end).execute()
                if not chunk_res.data:
                    break
                rows.extend(chunk_res.data)
            except Exception:
                logger.warning("list_jobs: chunk fetch failed at offset %d, returning %d partial rows", start, len(rows), exc_info=True)
                break

        return rows, total_count

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Return a single job by its primary key id or external_job_id."""
        try:
            result = (
                self._client.table("jobs")
                .select("*")
                .eq("id", job_id)
                .eq("is_active", True)
                .execute()
            )
            rows = result.data or []
            if rows:
                return rows[0]
        except Exception:
            pass

        try:
            result = (
                self._client.table("jobs")
                .select("*")
                .eq("external_job_id", job_id)
                .eq("is_active", True)
                .execute()
            )
            rows = result.data or []
            return rows[0] if rows else None
        except Exception:
            return None

    def get_priority_candidates(
        self,
        role: Optional[str] = None,
        location: Optional[str] = None,
        company: Optional[str] = None,
        employment_type: Optional[str] = None,
        desired_role: Optional[str] = None,
        limit_per_category: int = 500,
    ) -> list[dict[str, Any]]:
        """Retrieve verified active mass-hiring, fresher/entry, and semantic role-matched jobs.

        Guarantees high-priority opportunities outside the first 1000 rows
        enter the ranking universe without requiring an unbounded full-table scan.
        """
        from concurrent.futures import ThreadPoolExecutor

        cols = self._get_candidate_select_columns()

        def _fetch_mass() -> list[dict[str, Any]]:
            try:
                q = (
                    self._client.table("jobs")
                    .select(cols)
                    .eq("is_active", True)
                    .eq("mass_hiring", "VERIFIED_MASS_HIRING")
                    .eq("mass_hiring_status", "ACTIVE")
                )
                if location:
                    q = q.ilike("location", f"%{location}%")
                if company:
                    q = q.ilike("company", f"%{company}%")
                if employment_type:
                    q = q.ilike("employment_type", f"%{employment_type}%")
                res = q.execute()
                return res.data or []
            except Exception:
                logger.warning("get_priority_candidates: mass hiring query failed", exc_info=True)
                return []

        def _fetch_freshers() -> list[dict[str, Any]]:
            try:
                fresher_filter = (
                    "title.ilike.%intern%,title.ilike.%fresher%,title.ilike.%junior%,"
                    "title.ilike.%trainee%,title.ilike.%entry%,title.ilike.%associate%,"
                    "title.ilike.%early%career%,title.ilike.%early%talent%,title.ilike.%new%grad%,"
                    "experience_level.ilike.%entry%,experience_level.ilike.%fresher%,experience_level.ilike.%intern%"
                )
                q = (
                    self._client.table("jobs")
                    .select(cols)
                    .eq("is_active", True)
                    .or_(fresher_filter)
                )
                if location:
                    q = q.ilike("location", f"%{location}%")
                if company:
                    q = q.ilike("company", f"%{company}%")
                if employment_type:
                    q = q.ilike("employment_type", f"%{employment_type}%")
                res = q.execute()
                return res.data or []
            except Exception:
                logger.warning("get_priority_candidates: fresher query failed", exc_info=True)
                return []

        def _fetch_role() -> list[dict[str, Any]]:
            target = (role or desired_role or "").strip()
            if not target:
                return []
            try:
                import re
                from app.parsing.role_family import get_semantic_role_expansion

                expansions = get_semantic_role_expansion(target)
                clean_terms = [re.sub(r"[^\w\s]", "", exp).strip() for exp in expansions if exp.strip()]
                clean_terms = [t for t in clean_terms if t][:10]

                if len(clean_terms) > 1:
                    role_filter = ",".join(f"title.ilike.%{t.replace(' ', '%')}%" for t in clean_terms)
                    q = (
                        self._client.table("jobs")
                        .select(cols)
                        .eq("is_active", True)
                        .or_(role_filter)
                        .limit(limit_per_category)
                    )
                elif clean_terms:
                    clean_target = clean_terms[0].replace(" ", "%")
                    q = (
                        self._client.table("jobs")
                        .select(cols)
                        .eq("is_active", True)
                        .ilike("title", f"%{clean_target}%")
                        .limit(limit_per_category)
                    )
                else:
                    clean_target = target.replace(" ", "%")
                    q = (
                        self._client.table("jobs")
                        .select(cols)
                        .eq("is_active", True)
                        .ilike("title", f"%{clean_target}%")
                        .limit(limit_per_category)
                    )
                if location:
                    q = q.ilike("location", f"%{location}%")
                if company:
                    q = q.ilike("company", f"%{company}%")
                if employment_type:
                    q = q.ilike("employment_type", f"%{employment_type}%")
                res = q.execute()
                return res.data or []
            except Exception:
                logger.warning("get_priority_candidates: role query failed", exc_info=True)
                return []

        def _fetch_recent() -> list[dict[str, Any]]:
            try:
                q = (
                    self._client.table("jobs")
                    .select(cols)
                    .eq("is_active", True)
                    .order("posted_at", desc=True, nullsfirst=False)
                    .limit(limit_per_category)
                )
                if location:
                    loc_clean = location.strip()
                    if loc_clean.lower() in ("bangalore", "bengaluru"):
                        q = q.or_("location.ilike.%bangalore%,location.ilike.%bengaluru%")
                    else:
                        q = q.ilike("location", f"%{loc_clean}%")
                if company:
                    q = q.ilike("company", f"%{company}%")
                if employment_type:
                    q = q.ilike("employment_type", f"%{employment_type}%")
                res = q.execute()
                return res.data or []
            except Exception:
                logger.warning("get_priority_candidates: recent query failed", exc_info=True)
                return []

        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                f_mass = pool.submit(_fetch_mass)
                f_fresh = pool.submit(_fetch_freshers)
                f_role = pool.submit(_fetch_role)
                f_recent = pool.submit(_fetch_recent)

                mass_rows = f_mass.result()
                fresh_rows = f_fresh.result()
                role_rows = f_role.result()
                recent_rows = f_recent.result()

            seen: set[str] = set()
            out: list[dict[str, Any]] = []
            for r in mass_rows + fresh_rows + role_rows + recent_rows:
                rid = r.get("external_job_id") or r.get("id")
                if rid and rid not in seen:
                    seen.add(rid)
                    out.append(r)
            return out
        except Exception:
            logger.warning("get_priority_candidates failed", exc_info=True)
            return []

    def get_candidate_universe(
        self,
        page: int = 1,
        page_size: int = 1000,
        role: Optional[str] = None,
        location: Optional[str] = None,
        company: Optional[str] = None,
        employment_type: Optional[str] = None,
        desired_role: Optional[str] = None,
        sort: Optional[str] = None,
        limit_per_priority_category: int = 500,
    ) -> tuple[list[dict[str, Any]], int]:
        """Retrieve candidate universe concurrently (base pool + priority pools in a single pool).

        Preserves 100% candidate universe coverage while eliminating sequential wait latency.
        """
        from concurrent.futures import ThreadPoolExecutor

        cols = self._get_candidate_select_columns()

        def _fetch_base() -> tuple[list[dict[str, Any]], int]:
            try:
                q = self._client.table("jobs").select(cols, count="exact").eq("is_active", True)
                if role:
                    q = q.ilike("title", f"%{role}%")
                if location:
                    loc_clean = location.strip()
                    if loc_clean.lower() in ("bangalore", "bengaluru"):
                        q = q.or_("location.ilike.%bangalore%,location.ilike.%bengaluru%")
                    else:
                        q = q.ilike("location", f"%{loc_clean}%")
                if company:
                    q = q.ilike("company", f"%{company}%")
                if employment_type:
                    q = q.ilike("employment_type", f"%{employment_type}%")

                if sort == "newest":
                    q = q.order("posted_at", desc=True)
                elif sort == "oldest":
                    q = q.order("posted_at", desc=False)
                elif sort == "salary":
                    q = q.order("salary_max", desc=True)
                else:
                    q = q.order("created_at", desc=True)

                res = q.range(0, page_size - 1).execute()
                return (res.data or []), (res.count or 0)
            except Exception:
                logger.warning("get_candidate_universe: base query failed", exc_info=True)
                return [], 0

        def _fetch_mass() -> list[dict[str, Any]]:
            try:
                q = (
                    self._client.table("jobs")
                    .select(cols)
                    .eq("is_active", True)
                    .eq("mass_hiring", "VERIFIED_MASS_HIRING")
                    .eq("mass_hiring_status", "ACTIVE")
                )
                if location:
                    q = q.ilike("location", f"%{location}%")
                if company:
                    q = q.ilike("company", f"%{company}%")
                if employment_type:
                    q = q.ilike("employment_type", f"%{employment_type}%")
                res = q.execute()
                return res.data or []
            except Exception:
                logger.warning("get_candidate_universe: mass query failed", exc_info=True)
                return []

        def _fetch_freshers() -> list[dict[str, Any]]:
            try:
                fresher_filter = (
                    "title.ilike.%intern%,title.ilike.%fresher%,title.ilike.%junior%,"
                    "title.ilike.%trainee%,title.ilike.%entry%,title.ilike.%associate%,"
                    "title.ilike.%early%career%,title.ilike.%early%talent%,title.ilike.%new%grad%,"
                    "experience_level.ilike.%entry%,experience_level.ilike.%fresher%,experience_level.ilike.%intern%"
                )
                q = (
                    self._client.table("jobs")
                    .select(cols)
                    .eq("is_active", True)
                    .or_(fresher_filter)
                )
                if location:
                    q = q.ilike("location", f"%{location}%")
                if company:
                    q = q.ilike("company", f"%{company}%")
                if employment_type:
                    q = q.ilike("employment_type", f"%{employment_type}%")
                res = q.execute()
                return res.data or []
            except Exception:
                logger.warning("get_candidate_universe: fresher query failed", exc_info=True)
                return []

        def _fetch_role() -> list[dict[str, Any]]:
            target = (role or desired_role or "").strip()
            if not target:
                return []
            try:
                import re
                from app.parsing.role_family import get_semantic_role_expansion

                expansions = get_semantic_role_expansion(target)
                clean_terms = [re.sub(r"[^\w\s]", "", exp).strip() for exp in expansions if exp.strip()]
                clean_terms = [t for t in clean_terms if t][:10]

                if len(clean_terms) > 1:
                    role_filter = ",".join(f"title.ilike.%{t.replace(' ', '%')}%" for t in clean_terms)
                    q = (
                        self._client.table("jobs")
                        .select(cols)
                        .eq("is_active", True)
                        .or_(role_filter)
                        .limit(limit_per_priority_category)
                    )
                elif clean_terms:
                    clean_target = clean_terms[0].replace(" ", "%")
                    q = (
                        self._client.table("jobs")
                        .select(cols)
                        .eq("is_active", True)
                        .ilike("title", f"%{clean_target}%")
                        .limit(limit_per_priority_category)
                    )
                else:
                    clean_target = target.replace(" ", "%")
                    q = (
                        self._client.table("jobs")
                        .select(cols)
                        .eq("is_active", True)
                        .ilike("title", f"%{clean_target}%")
                        .limit(limit_per_priority_category)
                    )
                if location:
                    q = q.ilike("location", f"%{location}%")
                if company:
                    q = q.ilike("company", f"%{company}%")
                if employment_type:
                    q = q.ilike("employment_type", f"%{employment_type}%")
                res = q.execute()
                return res.data or []
            except Exception:
                logger.warning("get_candidate_universe: role query failed", exc_info=True)
                return []

        def _fetch_recent() -> list[dict[str, Any]]:
            try:
                q = (
                    self._client.table("jobs")
                    .select(cols)
                    .eq("is_active", True)
                    .order("posted_at", desc=True, nullsfirst=False)
                    .limit(limit_per_priority_category)
                )
                if location:
                    loc_clean = location.strip()
                    if loc_clean.lower() in ("bangalore", "bengaluru"):
                        q = q.or_("location.ilike.%bangalore%,location.ilike.%bengaluru%")
                    else:
                        q = q.ilike("location", f"%{loc_clean}%")
                if company:
                    q = q.ilike("company", f"%{company}%")
                if employment_type:
                    q = q.ilike("employment_type", f"%{employment_type}%")
                res = q.execute()
                return res.data or []
            except Exception:
                logger.warning("get_candidate_universe: recent query failed", exc_info=True)
                return []

        with ThreadPoolExecutor(max_workers=5) as pool:
            f_base = pool.submit(_fetch_base)
            f_mass = pool.submit(_fetch_mass)
            f_fresh = pool.submit(_fetch_freshers)
            f_role = pool.submit(_fetch_role)
            f_recent = pool.submit(_fetch_recent)

            base_rows, db_total = f_base.result()
            mass_rows = f_mass.result()
            fresh_rows = f_fresh.result()
            role_rows = f_role.result()
            recent_rows = f_recent.result()

        seen_ids = {r.get("external_job_id") or r.get("id") for r in base_rows}
        for r in mass_rows + fresh_rows + role_rows + recent_rows:
            kid = r.get("external_job_id") or r.get("id")
            if kid and kid not in seen_ids:
                seen_ids.add(kid)
                base_rows.append(r)

        return base_rows, db_total
