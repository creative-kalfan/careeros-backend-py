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
    "role_category", "application_deadline", "employment_type", "salary",
    "salary_min", "salary_max", "skills", "experience_level", "remote",
)

_DUPLICATE_KEY_CODE = "23505"

# Provenance columns written on insert/upgrade.
_PROVENANCE_FIELDS = (
    "source_tier", "source_provider", "canonical_url", "source_verified",
    "source_confidence", "company_website", "careers_url", "logo_url",
    "first_seen_at", "last_crawled_at", "source_history",
)


class JobRepository:
    """Data-access layer for the Supabase ``jobs`` table."""

    def __init__(self, client: Optional[Client] = None) -> None:
        self._client = client or get_service_client()
        # Column availability flags (probed lazily so tests can override).
        self._has_last_seen_at: Optional[bool] = None
        self._has_provenance: Optional[bool] = None

    # ------------------------------------------------------------------
    # Column probing
    # ------------------------------------------------------------------

    def _probe_has_last_seen_at(self) -> bool:
        """Check whether the ``last_seen_at`` column exists (migration 011)."""
        if self._has_last_seen_at is None:
            try:
                self._client.table("jobs").select("last_seen_at").limit(1).execute()
                self._has_last_seen_at = True
            except Exception:
                self._has_last_seen_at = False
        return self._has_last_seen_at

    def _probe_has_provenance(self) -> bool:
        """Check whether provenance columns exist (migration 016)."""
        if self._has_provenance is None:
            try:
                self._client.table("jobs").select("source_tier").limit(1).execute()
                self._has_provenance = True
            except Exception:
                self._has_provenance = False
        return self._has_provenance

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
    def _is_same_job(existing: dict[str, Any], row: dict[str, Any]) -> bool:
        """True when the existing row content matches the new row content."""
        for field in _CONTENT_FIELDS:
            if existing.get(field) != row.get(field):
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


    def upsert_jobs(self, jobs: list[NormalizedJob]) -> dict[str, int]:
        """Upsert a batch of normalized jobs idempotently.

        Counters: discovered, inserted, updated, unchanged, deduplicated, skipped.
        """
        inserted = 0
        updated = 0
        unchanged = 0
        deduplicated = 0
        skipped = 0
        seen_keys: set[tuple[str, str]] = set()

        now_iso = datetime.now(timezone.utc).isoformat()
        has_last_seen = self._probe_has_last_seen_at()

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
            if has_last_seen:
                row["last_seen_at"] = now_iso

            existing = self._coerce_row(self._find_by_identity(*key))
            row = self._apply_source_escalation(row, existing or None)

            if not existing:
                if self._probe_has_provenance():
                    row.setdefault("first_seen_at", now_iso)
                try:
                    self._client.table("jobs").insert(row).execute()
                    inserted += 1
                except APIError as exc:
                    args = str(getattr(exc, "args", ""))
                    code = str(getattr(exc, "code", "") or "")
                    if _DUPLICATE_KEY_CODE not in code and _DUPLICATE_KEY_CODE not in args:
                        raise
                    # Lost the insert race: another worker created the row.
                    winner = self._coerce_row(self._find_by_identity(*key))
                    if not winner:
                        deduplicated += 1
                        continue
                    row = job.to_db_row()
                    if has_last_seen:
                        row["last_seen_at"] = now_iso
                    row = self._apply_source_escalation(row, winner)
                    self._client.table("jobs").update(row).eq("id", winner["id"]).execute()
                    updated += 1
            elif self._is_same_job(existing, row):
                # Nothing changed: refresh last_seen only.
                if has_last_seen:
                    self._client.table("jobs").update({"last_seen_at": now_iso}).eq(
                        "id", existing["id"]
                    ).execute()
                unchanged += 1
            else:
                self._client.table("jobs").update(row).eq("id", existing["id"]).execute()
                updated += 1

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
        self, source_platform: Optional[str] = None, max_age_days: int = 30
    ) -> int:
        """Deactivate active jobs from a source that are no longer fresh.

        NO LONGER SEEN -> INACTIVE (never deleted). Scoped to
        ``source_platform`` when provided so one source can never deactivate
        another source's jobs. Returns the number of deactivated rows.
        """
        if not self._probe_has_last_seen_at():
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        query = (
            self._client.table("jobs")
            .select("id, posted_at, last_seen_at")
            .eq("is_active", True)
        )
        if source_platform:
            query = query.eq("source_platform", source_platform)

        try:
            result = query.execute()
        except APIError:
            logger.warning("deactivate_stale_jobs: query failed", exc_info=True)
            return 0

        count = 0
        for row in result.data or []:
            observed = row.get("posted_at") or row.get("last_seen_at")
            if observed and str(observed) >= cutoff:
                continue
            try:
                self._client.table("jobs").update({"is_active": False}).eq(
                    "id", row["id"]
                ).execute()
                count += 1
            except APIError:
                logger.warning("deactivate_stale_jobs: update failed for %s", row.get("id"))
        return count


    def deactivate_not_seen_since(
        self,
        source_platform: str,
        since_iso: str,
        careers_url: Optional[str] = None,
    ) -> int:
        """Deactivate active jobs from a source NOT observed since ``since_iso``.

        Called only after a SUCCESSFUL crawl of ``source_platform``: any still
        active row whose ``last_seen_at`` predates the crawl start was not seen
        during the crawl and is therefore considered closed at the source.
        Rows are deactivated (never deleted).

        When ``careers_url`` is provided (Firecrawl per-company crawls), the
        deactivation is additionally scoped to that careers URL so one
        company's successful crawl can never deactivate another company's
        jobs that share the same ``source_platform``.

        Returns the number of deactivated rows.
        """
        if not self._probe_has_last_seen_at():
            return 0

        query = (
            self._client.table("jobs")
            .select("id")
            .eq("is_active", True)
            .eq("source_platform", source_platform)
            .lt("last_seen_at", since_iso)
        )
        if careers_url:
            query = query.eq("careers_url", careers_url)

        try:
            result = query.execute()
        except APIError:
            logger.warning("deactivate_not_seen_since: query failed", exc_info=True)
            return 0

        count = 0
        for row in result.data or []:
            try:
                self._client.table("jobs").update({"is_active": False}).eq(
                    "id", row["id"]
                ).execute()
                count += 1
            except APIError:
                logger.warning(
                    "deactivate_not_seen_since: update failed for %s", row.get("id")
                )
        if count:
            logger.info(
                "deactivate_not_seen_since: %d rows deactivated (source=%s since=%s careers_url=%s)",
                count, source_platform, since_iso, careers_url or "-",
            )
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
        query = self._client.table("jobs").select("*", count="exact").eq("is_active", True)

        if role:
            query = query.ilike("title", f"%{role}%")
        if location:
            query = query.ilike("location", f"%{location}%")
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
            chunk_query = self._client.table("jobs").select("*").eq("is_active", True)
            if role:
                chunk_query = chunk_query.ilike("title", f"%{role}%")
            if location:
                chunk_query = chunk_query.ilike("location", f"%{location}%")
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

            chunk_res = chunk_query.range(start, end).execute()
            if not chunk_res.data:
                break
            rows.extend(chunk_res.data)

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