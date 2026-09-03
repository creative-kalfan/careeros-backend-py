"""Notification repository: RLS-scoped data access for notifications.

All methods take the RLS-authenticated async Supabase client from
``AuthContext`` so every query is scoped to ``auth.uid() = user_id``.
No service-role access is used for user-owned notification data.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class NotificationRepository:
    """Data-access layer for the ``notifications`` and
    ``notification_preferences`` tables."""

    # -- Notifications -------------------------------------------------------

    async def list_notifications(
        self,
        supabase: Any,
        user_id: str,
        is_read: Optional[bool] = None,
        channel: Optional[str] = None,
        type: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = (
            supabase.table("notifications")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(min(limit, 100))
        )
        if is_read is not None:
            query = query.eq("is_read", is_read)
        if channel:
            query = query.eq("delivery_channel", channel)
        if type:
            query = query.eq("type", type)
        result = await query.execute()
        return result.data or []

    async def get_unread_payload_job_ids(
        self,
        supabase: Any,
        user_id: str,
        type: str,
    ) -> set[str]:
        """Return job ids already referenced by unread notifications of a type.

        Single batched query used for deduplication (avoids N+1 inserts).
        """
        try:
            result = (
                await supabase.table("notifications")
                .select("payload_json")
                .eq("user_id", user_id)
                .eq("type", type)
                .eq("is_read", False)
                .execute()
            )
            ids: set[str] = set()
            for row in result.data or []:
                payload = row.get("payload_json") or {}
                job_id = payload.get("jobId") if isinstance(payload, dict) else None
                if job_id:
                    ids.add(str(job_id))
            return ids
        except Exception as exc:
            logger.debug("get_unread_payload_job_ids failed: %s", exc)
            return set()

    async def insert_notification(self, supabase: Any, row: dict[str, Any]) -> dict[str, Any]:
        result = await supabase.table("notifications").insert(row).execute()
        rows = result.data or []
        return rows[0] if rows else row

    async def mark_read(
        self, supabase: Any, user_id: str, notification_id: str
    ) -> Optional[dict[str, Any]]:
        result = (
            await supabase.table("notifications")
            .update({"is_read": True, "read_at": datetime.utcnow().isoformat()})
            .eq("id", notification_id)
            .eq("user_id", user_id)
            .select()
            .single()
            .execute()
        )
        return (result.data or [None])[0]

    async def mark_all_read(self, supabase: Any, user_id: str) -> int:
        result = (
            await supabase.table("notifications")
            .update({"is_read": True, "read_at": datetime.utcnow().isoformat()})
            .eq("user_id", user_id)
            .eq("is_read", False)
            .select("id")
            .execute()
        )
        return len(result.data or [])

    async def delete_notification(
        self, supabase: Any, user_id: str, notification_id: str
    ) -> bool:
        result = (
            await supabase.table("notifications")
            .delete()
            .eq("id", notification_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(result.data)

    # -- Preferences ---------------------------------------------------------

    async def get_preferences(
        self, supabase: Any, user_id: str
    ) -> Optional[dict[str, Any]]:
        try:
            result = (
                await supabase.table("notification_preferences")
                .select("*")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            return result.data or None
        except Exception as exc:
            logger.debug("get_preferences failed: %s", exc)
            return None

    async def upsert_preferences(
        self, supabase: Any, user_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        result = (
            await supabase.table("notification_preferences")
            .upsert({"user_id": user_id, **updates}, onConflict="user_id")
            .select()
            .single()
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else {"user_id": user_id, **updates}
