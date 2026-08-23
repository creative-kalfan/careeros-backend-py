"""Notification event subscriber.

Bridges domain events to the existing Notification Engine. Consumes the
already-ranked recommendation output carried by ``RecommendationGenerated``
and forwards it to ``NotificationService.notify_from_recommendations`` —
no score recalculation, no business-logic duplication.

The subscriber is intentionally thin: all threshold gating, deduplication,
and persistence remain inside the Notification Service.
"""

from __future__ import annotations

import logging
from typing import Any

from app.events.domain_event import DomainEvent, RecommendationGenerated

logger = logging.getLogger(__name__)


class NotificationEventSubscriber:
    """Generates notifications from recommendation domain events."""

    @property
    def name(self) -> str:
        return "NotificationEventSubscriber"

    @property
    def handled_types(self) -> list[str]:
        return [RecommendationGenerated.__name__]

    async def handle(self, event: DomainEvent, context: Any = None) -> None:
        if not isinstance(event, RecommendationGenerated):
            return
        if context is None:
            # Without request context (AuthContext) we cannot perform
            # RLS-scoped notification writes; skip rather than bypass RLS.
            logger.debug(
                "NotificationEventSubscriber skipping event %s: no context",
                event.event_id,
            )
            return

        from app.services.notifications.notification_service import NotificationService

        created = await NotificationService().notify_from_recommendations(
            context,
            event.recommendations,
        )
        logger.info(
            "NotificationEventSubscriber processed %s: user=%s notifications_created=%s",
            event.event_type,
            event.user_id,
            created,
        )
