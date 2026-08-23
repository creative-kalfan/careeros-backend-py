"""Notification service: orchestration/use-case layer.

Routes stay thin; all business logic flows through NotificationEngine
(templates + preference gates) and NotificationRepository (RLS-scoped).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.repositories.notification_repository import NotificationRepository
from app.services.notifications.notification_engine import (
    DEFAULT_PREFERENCES,
    NotificationEngine,
)

logger = logging.getLogger(__name__)

# Delivery channel for all current notifications (no email/push dispatchers exist).
IN_APP_CHANNEL = "in_app"


class NotificationService:
    """Use-case layer for listing, mutating, and generating notifications."""

    def __init__(
        self,
        repository: Optional[NotificationRepository] = None,
        engine: Optional[NotificationEngine] = None,
    ) -> None:
        self.repository = repository or NotificationRepository()
        self.engine = engine or NotificationEngine()

    # -- Retrieval -----------------------------------------------------------

    async def list_notifications(
        self,
        auth: Any,
        is_read: Optional[bool] = None,
        channel: Optional[str] = None,
        type: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        rows = await self.repository.list_notifications(
            auth.supabase,
            auth.user.id,
            is_read=is_read,
            channel=channel,
            type=type,
            limit=limit or 50,
        )
        return {"notifications": rows}

    # -- Read state ----------------------------------------------------------

    async def mark_read(self, auth: Any, notification_id: str) -> dict[str, Any]:
        row = await self.repository.mark_read(auth.supabase, auth.user.id, notification_id)
        return {"notification": row}

    async def mark_all_read(self, auth: Any) -> dict[str, Any]:
        count = await self.repository.mark_all_read(auth.supabase, auth.user.id)
        return {"notifications": [], "count": count}

    async def delete_notification(self, auth: Any, notification_id: str) -> bool:
        return await self.repository.delete_notification(
            auth.supabase, auth.user.id, notification_id
        )

    # -- Preferences ---------------------------------------------------------

    async def get_preferences(self, auth: Any) -> dict[str, Any]:
        row = await self.repository.get_preferences(auth.supabase, auth.user.id)
        if not row:
            return {
                "id": None,
                "user_id": auth.user.id,
                **DEFAULT_PREFERENCES,
            }
        return row

    async def update_preferences(self, auth: Any, updates: dict[str, Any]) -> dict[str, Any]:
        valid = self.engine.merge_preferences(updates)
        if not valid:
            raise ValueError("No valid fields to update")
        row = await self.repository.upsert_preferences(auth.supabase, auth.user.id, valid)
        return row

    # -- Generation ----------------------------------------------------------

    async def notify_from_recommendations(
        self,
        auth: Any,
        recommendations: list[dict[str, Any]],
    ) -> int:
        """Generate notifications from existing recommendation output.

        Consumes the already-ranked recommendation records (does NOT
        recalculate scores). For each recommendation whose score meets the
        user's high_match_threshold, creates a HIGH_MATCH_RECOMMENDATION
        notification (deduplicated per job while unread). If any qualifying
        recommendations were found, also emits a single
        NEW_RECOMMENDATION_AVAILABLE summary (deduped against unread).

        Returns the number of notifications created. Never raises to the
        caller's critical path — failures are logged and swallowed.
        """
        user_id = auth.user.id
        created = 0
        try:
            preferences = await self.get_preferences(auth)
        except Exception as exc:
            logger.debug("notify_from_recommendations: preferences unavailable: %s", exc)
            return 0

        try:
            existing_job_ids = await self.repository.get_unread_payload_job_ids(
                auth.supabase, user_id, "HIGH_MATCH_RECOMMENDATION"
            )
        except Exception as exc:
            logger.debug("notify_from_recommendations: dedupe query failed: %s", exc)
            existing_job_ids = set()

        qualifying = 0
        for rec in recommendations or []:
            score = rec.get("matchScore") or rec.get("match_score") or 0
            try:
                score = int(score)
            except (TypeError, ValueError):
                continue

            if not self.engine.should_notify_high_match(preferences, score):
                continue
            qualifying += 1

            job_id = str(rec.get("jobId") or rec.get("job_id") or "")
            if not job_id or job_id in existing_job_ids:
                continue

            job = rec.get("job") or {}
            template = self.engine.build_high_match_recommendation(
                {
                    "jobId": job_id,
                    "jobTitle": job.get("title") or "New opportunity",
                    "companyName": job.get("company") or job.get("company_name") or "",
                    "score": score,
                    "priority": rec.get("priority"),
                }
            )
            try:
                await self.repository.insert_notification(
                    auth.supabase,
                    {
                        "user_id": user_id,
                        "type": template["type"],
                        "title": template["title"],
                        "message": template["message"],
                        "payload_json": template["payload_json"],
                        "priority": template["priority"],
                        "is_read": False,
                        "delivery_channel": IN_APP_CHANNEL,
                    },
                )
                created += 1
                existing_job_ids.add(job_id)
            except Exception as exc:
                logger.debug("insert HIGH_MATCH notification failed: %s", exc)

        if qualifying > 0:
            try:
                summary_existing = await self.repository.get_unread_payload_job_ids(
                    auth.supabase, user_id, "NEW_RECOMMENDATION_AVAILABLE"
                )
                if not summary_existing:
                    template = self.engine.build_new_recommendation_available(qualifying)
                    await self.repository.insert_notification(
                        auth.supabase,
                        {
                            "user_id": user_id,
                            "type": template["type"],
                            "title": template["title"],
                            "message": template["message"],
                            "payload_json": template["payload_json"],
                            "priority": template["priority"],
                            "is_read": False,
                            "delivery_channel": IN_APP_CHANNEL,
                        },
                    )
                    created += 1
            except Exception as exc:
                logger.debug("insert NEW_RECOMMENDATION_AVAILABLE failed: %s", exc)

        return created

    async def create_notification(
        self,
        auth: Any,
        type: str,
        title: str,
        message: str,
        payload: Optional[dict[str, Any]] = None,
        priority: str = "medium",
    ) -> dict[str, Any]:
        """Generic creation entry point for internal producers."""
        template = self.engine.build_generic(type, title, message, payload, priority)
        return await self.repository.insert_notification(
            auth.supabase,
            {
                "user_id": auth.user.id,
                "type": template["type"],
                "title": template["title"],
                "message": template["message"],
                "payload_json": template["payload_json"],
                "priority": template["priority"],
                "is_read": False,
                "delivery_channel": IN_APP_CHANNEL,
            },
        )
