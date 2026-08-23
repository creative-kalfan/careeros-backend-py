"""Event handler protocol and registry."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.events.domain_event import DomainEvent

# Wildcard event type: handlers declaring this string receive every event.
WILDCARD = "*"


@runtime_checkable
class EventHandler(Protocol):
    """A subscribed handler for one or more domain event types.

    Implementations declare the event type names they consume via
    ``handled_types`` (a list of ``DomainEvent.event_type`` strings, or
    ``[WILDCARD]`` to observe all events).

    ``context`` is the opaque request-scoped object supplied at publish
    time (in CareerOS, typically the RLS ``AuthContext``). Handlers that
    touch user-owned data MUST scope their queries through it.
    """

    @property
    def name(self) -> str: ...

    @property
    def handled_types(self) -> list[str]: ...

    async def handle(self, event: DomainEvent, context: object | None) -> None: ...


class HandlerRegistry:
    """Registration-order-preserving handler registry.

    Multiple handlers may subscribe to the same event type; dispatch order
    is deterministic (registration order, wildcards last). Instances are
    cheap — create one per bus; no process-global mutable state.
    """

    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []

    def register(self, handler: EventHandler) -> None:
        if any(existing.name == handler.name for existing in self._handlers):
            raise ValueError(f"Handler already registered: {handler.name}")
        self._handlers.append(handler)

    def get_handlers(self, event_type: str) -> list[EventHandler]:
        """Typed handlers first (registration order), then wildcards."""
        typed = [h for h in self._handlers if event_type in h.handled_types]
        wildcards = [h for h in self._handlers if WILDCARD in h.handled_types]
        return typed + wildcards

    def list_handlers(self) -> list[EventHandler]:
        return list(self._handlers)
