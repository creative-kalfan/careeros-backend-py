"""Focused tests for the in-process domain event bus.

Covers: typed registration, deterministic dispatch order, multiple handlers
per event, wildcard handlers, handler failure isolation, dispatch report
contents, and context propagation.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.events import (
    ApplicationStatusChanged,
    DomainEvent,
    EventBus,
    HandlerRegistry,
    RecommendationGenerated,
    get_event_bus,
    reset_event_bus,
)


class RecordingHandler:
    """Test double: records events, optionally raises."""

    def __init__(
        self,
        name: str,
        handled_types: list[str],
        fail: bool = False,
        delay: float = 0.0,
    ) -> None:
        self._name = name
        self._handled_types = handled_types
        self.fail = fail
        self.delay = delay
        self.received: list[tuple[DomainEvent, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def handled_types(self) -> list[str]:
        return self._handled_types

    async def handle(self, event: DomainEvent, context: Any = None) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        self.received.append((event, context))
        if self.fail:
            raise RuntimeError(f"{self._name} exploded")


@pytest.fixture(autouse=True)
def _reset_default_bus() -> None:
    reset_event_bus()
    yield
    reset_event_bus()


class TestRegistry:
    def test_duplicate_names_rejected(self) -> None:
        registry = HandlerRegistry()
        registry.register(RecordingHandler("dup", ["X"]))
        with pytest.raises(ValueError):
            registry.register(RecordingHandler("dup", ["Y"]))

    def test_wildcards_dispatch_after_typed_handlers(self) -> None:
        registry = HandlerRegistry()
        wild = RecordingHandler("wild", ["*"])
        typed_b = RecordingHandler("typed-b", [RecommendationGenerated.__name__])
        typed_a = RecordingHandler("typed-a", [RecommendationGenerated.__name__])
        registry.register(wild)
        registry.register(typed_b)
        registry.register(typed_a)

        handlers = registry.get_handlers(RecommendationGenerated.__name__)
        assert [h.name for h in handlers] == ["typed-b", "typed-a", "wild"]


class TestEventBus:
    def test_multiple_handlers_all_receive_event_in_order(self) -> None:
        bus = EventBus()
        first = RecordingHandler("first", [RecommendationGenerated.__name__])
        second = RecordingHandler("second", [RecommendationGenerated.__name__])
        bus.subscribe(first)
        bus.subscribe(second)

        event = RecommendationGenerated(user_id="u1", aggregate_id="u1")
        report = asyncio.run(bus.publish(event))

        assert report.handler_count == 2
        assert report.succeeded
        assert [r.handler_name for r in report.results] == ["first", "second"]
        assert first.received[0][0] is event
        assert second.received[0][0] is event

    def test_handler_failure_is_isolated_and_reported(self) -> None:
        bus = EventBus()
        failing = RecordingHandler("failing", [RecommendationGenerated.__name__], fail=True)
        healthy = RecordingHandler("healthy", [RecommendationGenerated.__name__])
        bus.subscribe(failing)
        bus.subscribe(healthy)

        report = asyncio.run(bus.publish(RecommendationGenerated(user_id="u1")))

        # Healthy handler still ran; failure recorded, not raised.
        assert not report.succeeded
        assert len(report.failures) == 1
        assert "RuntimeError" in (report.failures[0].error or "")
        assert healthy.received, "isolation broken: healthy handler skipped"

    def test_no_subscribers_yields_empty_report(self) -> None:
        bus = EventBus()
        report = asyncio.run(bus.publish(ApplicationStatusChanged(user_id="u1")))
        assert report.handler_count == 0
        assert report.results == []
        assert report.succeeded

    def test_context_propagates_to_handlers(self) -> None:
        bus = EventBus()
        handler = RecordingHandler("ctx", [RecommendationGenerated.__name__])
        bus.subscribe(handler)

        sentinel = object()
        asyncio.run(bus.publish(RecommendationGenerated(user_id="u1"), context=sentinel))
        assert handler.received[0][1] is sentinel

    def test_deterministic_dispatch_across_runs(self) -> None:
        outcomes = []
        for _ in range(3):
            bus = EventBus()
            order: list[str] = []

            class OrderHandler(RecordingHandler):
                pass

            h1 = RecordingHandler("h1", [RecommendationGenerated.__name__], delay=0.01)
            h2 = RecordingHandler("h2", [RecommendationGenerated.__name__])

            async def spy_handle(self: Any, event: Any, context: Any) -> None:  # type: ignore[no-untyped-def]
                await RecordingHandler.handle(self, event, context)

            h1.handle = spy_handle.__get__(h1)  # type: ignore[method-assign]
            h2.handle = spy_handle.__get__(h2)  # type: ignore[method-assign]

            original_h1 = h1.handle  # type: ignore[attr-defined]
            original_h2 = h2.handle  # type: ignore[attr-defined]

            async def wrapped1(event: Any, context: Any = None) -> None:
                order.append("h1-start")
                await original_h1(event, context)

            async def wrapped2(event: Any, context: Any = None) -> None:
                order.append("h2")
                await original_h2(event, context)

            h1.handle = wrapped1  # type: ignore[method-assign]
            h2.handle = wrapped2  # type: ignore[method-assign]

            bus.subscribe(h2)
            bus.subscribe(h1)
            asyncio.run(bus.publish(RecommendationGenerated(user_id="u1")))
            outcomes.append(tuple(order))

        assert outcomes[0] == outcomes[1] == outcomes[2]

    def test_publish_rejects_non_domain_events(self) -> None:
        bus = EventBus()
        with pytest.raises(TypeError):
            asyncio.run(bus.publish({"event_type": "NotAnEvent"}))  # type: ignore[arg-type]


class TestDefaultRuntimeBus:
    def test_default_bus_has_notification_subscriber(self) -> None:
        bus = get_event_bus()
        assert "NotificationEventSubscriber" in bus.list_handlers()

    def test_reset_then_get_creates_fresh_instance(self) -> None:
        first = get_event_bus()
        reset_event_bus()
        second = get_event_bus()
        assert first is not second
