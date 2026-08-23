"""Domain events package.

Internal, typed, in-process pub/sub for CareerOS domain events.

Usage:
    from app.events import RecommendationGenerated, get_event_bus

    report = await get_event_bus().publish(RecommendationGenerated(...), context=auth)

Handler failures are isolated and logged; publishing never breaks the
originating business operation. See ``app/events/bus.py`` docstring.
"""

from app.events.bus import DispatchReport, EventBus, HandlerResult
from app.events.domain_event import (
    ApplicationStatusChanged,
    DomainEvent,
    JobIngested,
    NotificationCreated,
    RecommendationGenerated,
    ResumeParsed,
)
from app.events.registry import EventHandler, HandlerRegistry, WILDCARD
from app.events.runtime import create_event_bus, get_event_bus, reset_event_bus

__all__ = [
    "ApplicationStatusChanged",
    "DispatchReport",
    "DomainEvent",
    "EventHandler",
    "EventBus",
    "HandlerRegistry",
    "HandlerResult",
    "JobIngested",
    "NotificationCreated",
    "RecommendationGenerated",
    "ResumeParsed",
    "WILDCARD",
    "create_event_bus",
    "get_event_bus",
    "reset_event_bus",
]
