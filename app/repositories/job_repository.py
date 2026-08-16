"""Job repository: persistence and querying of jobs in Supabase.

Uses the service-role client so ingestion can upsert jobs regardless of RLS.
Idempotency is achieved by upserting on the ``external_job_id`` + ``source_platform``
unique key (the existing schema already has these columns).
"""

from __future__ import annotations

from typing import Any, Optional

from supabase import Client

from app.db.supabase import get_service_client
from app.models.job import NormalizedJob


class JobRepository:
    """Data-access layer for the Supabase ``jobs`` table."""

    def __init__(self, client: Optional[Client] = None) -> None:
        self._client = client or get_service_client()

    def upsert_jobs(self, jobs: list[NormalizedJob]) -> dict[str, int]:
        """Upsert a batch of normalized jobs idempotently.

        Returns counts: {"inserted": n, "updated": n, "skipped": n}.
        """
        inserted = 0
        updated = 0
        skipped = 0

        for job in jobs:
            if not job.external_job_id or not job.source_platform:
                skipped += 1
                continue

            row = job.to_db_row()

            # Check if the job already exists by external identity.
            existing = (
                self._client.table("jobs")
                .select("id")
                .eq("external_job_id", job.external_job_id)
                .eq("source_platform", job.source_platform)
                .execute()
            )
            existing_rows = existing.data or []

            if existing_rows:
                # Update the existing row (preserve its id).
                self._client.table("jobs").update(row).eq(
                    "id", existing_rows[0]["id"]
                ).execute()
                updated += 1
            else:
                self._client.table("jobs").insert(row).execute()
                inserted += 1

        return {"inserted": inserted, "updated": updated, "skipped": skipped}

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
    ) -> tuple[list[dict[str, Any]], int]:
        """Return a page of active jobs plus the total count.

        Filters: role (title ilike), location (ilike), role_category (eq).
        """
        offset = (page - 1) * page_size
        query = self._client.table("jobs").select("*", count="exact").eq("is_active", True)

        if role:
            query = query.ilike("title", f"%{role}%")
        if location:
            query = query.ilike("location", f"%{location}%")
        if role_category:
            query = query.eq("role_category", role_category)

        query = query.order("created_at", desc=True).range(offset, offset + page_size - 1)
        result = query.execute()
        return (result.data or []), (result.count or 0)

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Return a single job by its primary key id."""
        result = (
            self._client.table("jobs")
            .select("*")
            .eq("id", job_id)
            .eq("is_active", True)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None