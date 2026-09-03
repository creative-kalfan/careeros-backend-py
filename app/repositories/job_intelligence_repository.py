"""Repository for job intelligence data access."""

from __future__ import annotations

import logging
from typing import Any, Optional

from postgrest.exceptions import APIError
from supabase import Client

from app.db.supabase import get_service_client
from app.models.job_intelligence import JobIntelligence

logger = logging.getLogger(__name__)


class JobIntelligenceRepository:
    """Data-access layer for the job_intelligence table."""

    def __init__(self, client: Optional[Client] = None) -> None:
        self._client = client or get_service_client()

    def get_by_job_id(self, job_id: str) -> Optional[dict[str, Any]]:
        """Return the current intelligence for a job, or None."""
        try:
            result = (
                self._client.table("job_intelligence")
                .select("*")
                .eq("job_id", job_id)
                .order("generated_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = result.data or []
            return rows[0] if rows else None
        except APIError:
            return None
        except Exception:
            return None

    def upsert(self, intelligence: JobIntelligence) -> dict[str, Any]:
        """Create or update intelligence for a job.

        Returns the inserted/updated row.
        """
        row = intelligence.to_db_row()
        try:
            existing = (
                self._client.table("job_intelligence")
                .select("id")
                .eq("job_id", intelligence.job_id)
                .execute()
            )
        except APIError:
            return row
        except Exception:
            return row

        existing_rows = existing.data or []

        try:
            if existing_rows:
                result = (
                    self._client.table("job_intelligence")
                    .update(row)
                    .eq("job_id", intelligence.job_id)
                    .execute()
                )
            else:
                result = self._client.table("job_intelligence").insert(row).execute()
        except APIError:
            return row
        except Exception:
            return row

        rows = result.data or []
        return rows[0] if rows else row
