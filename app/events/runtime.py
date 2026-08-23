"""Event bus runtime: composition root and process-level accessor.

``get_event_bus()`` returns the lazily-created default bus wired with the
production subscriber set (currently: NotificationEventSubscriber). Tests
use ``reset_event_bus()`` or construct isolated ``EventBus`` instances
directly to avoid shared state.
"""

from __future__ import annotations

import logging
import threading

from app.events.bus import EventBus
from app.events.subscribers.notification_subscriber import NotificationEventSubscriber

logger = logging.getLogger(__name__)

_default_bus: EventBus | None = None
_bus_lock = threading.Lock()


def create_event_bus() -> EventBus:
    """Build a fully-wired event bus (fresh instance, no global state)."""
    bus = EventBus()
    bus.subscribe(NotificationEventSubscriber())
    return bus


def get_event_bus() -> EventBus:
    """Return the process-wide default bus, creating it on first use."""
    global _default_bus
    if _default_bus is None:
        with _bus_lock:
            if _default_bus is None:
                _default_bus = create_event_bus()
                logger.info("Domain event bus initialized")
    return _default_bus


def reset_event_bus() -> None:
    """Dispose the default bus (test/ops helper)."""
    global _default_bus
    with _bus_lock:
        _default_bus = None
