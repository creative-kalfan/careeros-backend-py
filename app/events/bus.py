"""In-process domain event bus.

FAILURE SEMANTICS (deliberate design decision):
    business operation succeeds
        -> event published
            -> handler raises
                -> failure logged + recorded in DispatchReport
                -> originating operation remains successful

Handler failures are ISOLATED: one failing handler never prevents other
handlers from running and never propagates into the publisher's business
flow. Errors are logged (never silently swallowed) and returned in the
:class:`DispatchReport` for programmatic inspection.

Dispatch is sequential and deterministic: typed handlers run in
registration order, wildcard handlers after them. This makes behavior
reproducible in tests and predictable in production.

The bus is broker-independent. Domain code publishes through this
abstraction only; a future durable implementation (e.g. ARQ-backed or a
message broker) can implement the same publish/subscribe surface without
touching domain services.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.events.domain_event import DomainEvent
from app.events.registry import HandlerRegistry

logger = logging.getLogger(__name__)


@dataclass
class HandlerResult:
    """Outcome of dispatching one event to one handler."""

    handler_name: str
    success: bool
    error: Optional[str] = None


@dataclass
class DispatchReport:
    """Aggregate outcome of publishing a single event."""

    event_id: str
    event_type: str
    handler_count: int = 0
    results: list[HandlerResult] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def failures(self) -> list[HandlerResult]:
        return [r for r in self.results if not r.success]


class EventBus:
    """Typed publish/subscribe bus for in-process domain events."""

    def __init__(self, registry: HandlerRegistry | None = None) -> None:
        self._registry = registry or HandlerRegistry()

    # -- Subscription --------------------------------------------------------

    def subscribe(self, handler: EventHandler) -> None:
        """Register a handler. Duplicate handler names are rejected."""
        self._registry.register(handler)

    def list_handlers(self) -> list[str]:
        return [h.name for h in self._registry.list_handlers()]

    # -- Publishing ----------------------------------------------------------

    async def publish(
        self,
        event: DomainEvent,
        context: Any = None,
    ) -> DispatchReport:
        """Publish an event to all subscribed handlers.

        Never raises due to handler failures; only raises if ``event`` is
        not a valid DomainEvent (a programming error).
        """
        if not isinstance(event, DomainEvent):
            raise TypeError(f"publish expects a DomainEvent, got {type(event)!r}")

        handlers = self._registry.get_handlers(event.event_type)
        report = DispatchReport(
            event_id=event.event_id,
            event_type=event.event_type,
            handler_count=len(handlers),
        )

        for handler in handlers:
            result = await self._dispatch_one(event, handler, context)
            report.results.append(result)

        return report

    async def _dispatch_one(
        self,
        event: DomainEvent,
        handler: EventHandler,
        context: Any,
    ) -> HandlerResult:
        try:
            await handler.handle(event, context)
            return HandlerResult(handler_name=handler.name, success=True)
        except Exception as exc:  # noqa: BLE001 — isolation is the point
            logger.warning(
                "Event handler failed: event_type=%s event_id=%s handler=%s error=%s",
                event.event_type,
                event.event_id,
                handler.name,
                exc,
                exc_info=True,
            )
            return HandlerResult(
                handler_name=handler.name,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )
