"""Application repository: persistence for applications and their child entities.

All queries are scoped to a user through the RLS-authenticated Supabase client
(the per-request ``AuthContext``). Business logic lives in the service layer;
this class owns raw persistence only.

Ownership rule: every child write is preceded by an explicit ownership check on
the parent application (``get_application``), complementing the RLS policies so
a user can never read or mutate another user's application or child rows.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CHILD_TABLES = {
    "interviews": "application_interviews",
    "assessments": "application_assessments",
    "contacts": "application_contacts",
    "follow_ups": "application_follow_ups",
    "events": "application_events",
    "attachments": "application_attachments",
}


def _first(data: Any) -> Optional[dict[str, Any]]:
    """Return the single row dict from a PostgREST result, or None."""
    if isinstance(data, list):
        return data[0] if data else None
    return data if isinstance(data, dict) and data else None


class DuplicateApplicationError(Exception):
    """Raised when a job is already tracked as an application by the user."""


class ApplicationRepository:
    """Data-access layer for the applications domain."""

    # -- Applications ---------------------------------------------------------

    async def list_applications(
        self,
        supabase: Any,
        user_id: str,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        query = supabase.table("applications").select("*", count="exact").eq("user_id", user_id)
        if status:
            query = query.eq("status", status)
        if search:
            term = f"%{search}%"
            query = query.or_(f"job_title.ilike.{term},company_name.ilike.{term}")
        query = query.order("application_date", desc=True)
        offset = (page - 1) * page_size
        query = query.range(offset, offset + page_size - 1)
        result = await query.execute()
        total = (
            result.count
            if hasattr(result, "count") and result.count is not None
            else len(result.data or [])
        )
        return (result.data or []), (total or 0)

    async def get_application(
        self, supabase: Any, user_id: str, application_id: str
    ) -> Optional[dict[str, Any]]:
        result = await (
            supabase.table("applications")
            .select("*")
            .eq("id", application_id)
            .eq("user_id", user_id)
            .execute()
        )
        return _first(result.data)

    async def find_by_job(
        self, supabase: Any, user_id: str, job_id: str
    ) -> Optional[dict[str, Any]]:
        result = await (
            supabase.table("applications")
            .select("*")
            .eq("user_id", user_id)
            .eq("job_id", job_id)
            .execute()
        )
        return _first(result.data)

    async def create_application(
        self, supabase: Any, user_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {"user_id": user_id, **data}
        result = await supabase.table("applications").insert(payload).execute()
        row = _first(result.data)
        if row is None:
            raise RuntimeError("Application insert returned no row")
        return row

    async def update_application(
        self, supabase: Any, user_id: str, application_id: str, updates: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        result = await (
            supabase.table("applications")
            .update(updates)
            .eq("id", application_id)
            .eq("user_id", user_id)
            .select("*")
            .execute()
        )
        return _first(result.data)

    async def delete_application(self, supabase: Any, user_id: str, application_id: str) -> bool:
        result = await (
            supabase.table("applications")
            .delete()
            .eq("id", application_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(result.data or [])
# -- Child rows (scoped through ownership check in the service) ----------

    async def list_child(self, supabase: Any, application_id: str, table: str) -> list[dict[str, Any]]:
        result = await (
            supabase.table(table).select("*").eq("application_id", application_id).execute()
        )
        return result.data or []

    async def create_child(
        self, supabase: Any, application_id: str, table: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        result = await (
            supabase.table(table).insert({"application_id": application_id, **data}).execute()
        )
        row = _first(result.data)
        if row is None:
            raise RuntimeError(f"Insert into {table} returned no row")
        return row

    async def update_child(
        self,
        supabase: Any,
        application_id: str,
        table: str,
        child_id: str,
        updates: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        result = await (
            supabase.table(table)
            .update(updates)
            .eq("id", child_id)
            .eq("application_id", application_id)
            .select("*")
            .execute()
        )
        return _first(result.data)

    async def delete_child(
        self, supabase: Any, application_id: str, table: str, child_id: str
    ) -> bool:
        result = await (
            supabase.table(table)
            .delete()
            .eq("id", child_id)
            .eq("application_id", application_id)
            .execute()
        )
        return bool(result.data or [])

    async def get_child(
        self, supabase: Any, application_id: str, table: str, child_id: str
    ) -> Optional[dict[str, Any]]:
        result = await (
            supabase.table(table)
            .select("*")
            .eq("id", child_id)
            .eq("application_id", application_id)
            .execute()
        )
        return _first(result.data)

    # -- Timeline events -----------------------------------------------------

    async def create_event(
        self,
        supabase: Any,
        application_id: str,
        event_type: str,
        title: str,
        detail: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        result = await (
            supabase.table("application_events")
            .insert(
                {
                    "application_id": application_id,
                    "event_type": event_type,
                    "title": title,
                    "detail": detail,
                    "metadata": metadata or {},
                }
            )
            .execute()
        )
        row = _first(result.data)
        if row is None:
            raise RuntimeError("Event insert returned no row")
        return row

    async def list_events(self, supabase: Any, application_id: str) -> list[dict[str, Any]]:
        return await self.list_child(supabase, application_id, "application_events")
    async def list_events_for_users(self, supabase: Any, app_ids):
        if not app_ids:
            return []
        result = await (
            supabase.table("application_events")
            .select("*")
            .in_("application_id", app_ids)
            .order("created_at", desc=False)
            .execute()
        )
        return result.data or []

    # -- Enrichment (nested children for list/detail responses) ---------------

    async def enrich_applications(
        self, supabase: Any, rows: list[dict[str, Any]], app_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Attach interviews/assessments/contacts/follow-ups/events to rows.

        Uses batched ``IN`` queries keyed on the owned application ids so we
        avoid N+1 lookups and stay fully scoped to the user.
        """
        if not rows:
            return rows
        children: dict[str, list[dict[str, Any]]] = {
            "interviews": [],
            "assessments": [],
            "contacts": [],
            "follow_ups": [],
            "events": [],
            "attachments": [],
        }
        for key, table in _CHILD_TABLES.items():
            try:
                result = await (
                    supabase.table(table)
                    .select("*")
                    .in_("application_id", app_ids)
                    .execute()
                )
                children[key] = result.data or []
            except Exception as exc:  # noqa: BLE001 - resilient to missing tables
                logger.debug("enrich %s failed: %s", table, exc)
                children[key] = []

        grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for key, items in children.items():
            for item in items:
                aid = str(item.get("application_id") or "")
                grouped.setdefault(aid, {}).setdefault(key, []).append(item)

        enriched = []
        for row in rows:
            aid = str(row.get("id") or "")
            g = grouped.get(aid, {})
            clone = dict(row)
            clone["interviews"] = _order_child(g.get("interviews", []), "scheduled_at")
            clone["assessments"] = _order_child(g.get("assessments", []), "due_at")
            clone["contacts"] = g.get("contacts", [])
            clone["follow_ups"] = _order_child(g.get("follow_ups", []), "due_at")
            clone["attachments"] = g.get("attachments", [])
            clone["events"] = g.get("events", [])
            enriched.append(clone)
        return enriched

    # -- Statistics ----------------------------------------------------------

    async def get_status_counts(
        self, supabase: Any, user_id: str, archived: bool = False
    ) -> list[dict[str, Any]]:
        try:
            result = await (
                supabase.table("applications")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            rows = result.data or []
        except Exception as exc:
            logger.warning("get_status_counts query failed for user %s: %s", user_id, exc)
            rows = []
        # Keep the DB query single-`eq` (mock/RLS friendly); filter archived here.
        if archived:
            return [r for r in rows if r.get("archived")]
        return [r for r in rows if not r.get("archived")]


def _order_child(items: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    """Sort child rows by a nullable datetime string column (blanks last)."""

    def _key(item: dict[str, Any]) -> str:
        val = item.get(field)
        return val or "9999-12-31T00:00:00"

    try:
        return sorted(items, key=_key)
    except TypeError:  # pragma: no cover - mixed types
        return items
