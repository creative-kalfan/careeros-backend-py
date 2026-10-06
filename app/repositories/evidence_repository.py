"""Repository for Evidence Bank items and bullet citations."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.db.supabase import get_service_client

logger = logging.getLogger(__name__)

_PROBE_CACHE_EVIDENCE: dict[str, bool] = {}


class EvidenceRepository:
    """Data-access for evidence_items and bullet_evidence with owner scoping."""

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
        """Check if evidence_items table exists."""
        client = self._get_client()
        key = self._probe_key(client)
        cached = _PROBE_CACHE_EVIDENCE.get(key)
        if cached is None:
            try:
                client.table("evidence_items").select("id").limit(1).execute()
                cached = True
            except Exception:
                cached = False
            _PROBE_CACHE_EVIDENCE[key] = cached
        return cached

    def add_evidence_item(
        self,
        user_id: str,
        item_type: str,
        title: str,
        content: dict[str, Any],
        origin: str = "user_entered",
        user_verified: bool = False,
    ) -> Optional[dict[str, Any]]:
        """Add an evidence item to the user's evidence bank."""
        if not self.is_available():
            return None

        try:
            payload = {
                "user_id": user_id,
                "type": item_type,
                "title": title,
                "content": content,
                "origin": origin,
                "user_verified": user_verified,
            }
            res = self._get_client().table("evidence_items").insert(payload).execute()
            data = getattr(res, "data", None)
            return data[0] if data and isinstance(data, list) else None
        except Exception as exc:
            logger.warning("Failed to insert evidence item: %s", exc)
            return None

    def get_user_evidence(self, user_id: str) -> list[dict[str, Any]]:
        """Get all evidence items for a user."""
        if not self.is_available():
            return []

        try:
            res = (
                self._get_client()
                .table("evidence_items")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .execute()
            )
            return getattr(res, "data", None) or []
        except Exception as exc:
            logger.warning("Failed to get user evidence: %s", exc)
            return []

    def attach_bullet_evidence(
        self,
        version_id: str,
        bullet_ref: str,
        evidence_ids: list[str],
    ) -> bool:
        """Record evidence citations for a generated bullet."""
        if not self.is_available() or not evidence_ids:
            return False

        try:
            rows = [
                {"version_id": version_id, "bullet_ref": bullet_ref, "evidence_id": eid}
                for eid in evidence_ids
            ]
            self._get_client().table("bullet_evidence").upsert(
                rows, on_conflict="version_id,bullet_ref,evidence_id"
            ).execute()
            return True
        except Exception as exc:
            logger.warning("Failed to attach bullet evidence: %s", exc)
            return False

    def get_bullet_evidence(self, version_id: str, bullet_ref: str) -> list[dict[str, Any]]:
        """Retrieve evidence citations for a bullet."""
        if not self.is_available():
            return []

        try:
            res = (
                self._get_client()
                .table("bullet_evidence")
                .select("evidence_id, evidence_items(*)")
                .eq("version_id", version_id)
                .eq("bullet_ref", bullet_ref)
                .execute()
            )
            return getattr(res, "data", None) or []
        except Exception:
            return []
