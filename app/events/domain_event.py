"""Domain event abstraction.

Typed, serializable-by-construction domain events. Events are pure data:
they never carry database clients, credentials, or behavior. Request-scoped
context (e.g. the RLS AuthContext) travels alongside the event at dispatch
time via ``EventBus.publish(event, context=...)`` — NOT inside the payload —
so events remain safe to log, inspect, and later route through a durable
broker without leaking secrets.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all CareerOS domain events.

    Subclasses set ``event_type`` and declare typed payload fields.
    ``event_id`` / ``occurred_at`` default deterministically at construction.
    """

    event_type: str = field(init=False)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=_utcnow)
    aggregate_type: str = "unknown"
    aggregate_id: str = ""
    user_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not getattr(self, "event_type", None):
            object.__setattr__(self, "event_type", type(self).__name__)

    def to_dict(self) -> dict[str, Any]:
        """Envelope representation (for logging / future durable transport)."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "user_id": self.user_id,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Concrete events — smallest useful set across existing stable domains.
# Events without a publisher yet document the extension surface; wire them
# as their producer services adopt the bus.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecommendationGenerated(DomainEvent):
    """Emitted after a recommendation generation pass completes.

    ``recommendations`` carries the already-ranked output records so
    consumers (e.g. notifications) never recalculate scores.
    """

    aggregate_type: str = "recommendation"
    recommendations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ApplicationStatusChanged(DomainEvent):
    """A tracked application moved between statuses."""

    aggregate_type: str = "application"
    application_id: str = ""
    previous_status: str = ""
    new_status: str = ""


@dataclass(frozen=True)
class ResumeParsed(DomainEvent):
    """Background resume parsing finished (success or failure)."""

    aggregate_type: str = "resume"
    resume_id: str = ""
    parse_status: str = ""


@dataclass(frozen=True)
class JobIngested(DomainEvent):
    """A job batch was ingested/upserted by a crawler source."""

    aggregate_type: str = "job"
    source_platform: str = ""
    jobs_processed: int = 0


@dataclass(frozen=True)
class NotificationCreated(DomainEvent):
    """An in-app notification was created for a user."""

    aggregate_type: str = "notification"
    notification_type: str = ""
