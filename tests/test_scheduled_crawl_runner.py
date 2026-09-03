"""Tests for the scheduled crawl runner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.jobs.scheduled_crawl_runner import ScheduledCrawlRunner, CRAWL_TARGETS


@pytest.mark.asyncio
async def test_run_once_enqueues_crawl_jobs():
    """run_once should enqueue individual crawl jobs instead of running them."""
    runner = ScheduledCrawlRunner()
    runner._enqueue_crawl = AsyncMock()

    results = await runner.run_once()

    # Should enqueue one job per crawl target
    assert runner._enqueue_crawl.await_count == len(CRAWL_TARGETS)
    for source, slug in CRAWL_TARGETS:
        runner._enqueue_crawl.assert_any_await(source, slug)
    # Results should indicate all jobs were enqueued
    assert all(v == "enqueued" for v in results.values())


@pytest.mark.asyncio
async def test_run_once_handles_enqueue_failure():
    """A failure in one enqueue should not prevent the others."""
    runner = ScheduledCrawlRunner()
    call_count = 0

    async def mock_enqueue(source: str, slug: str) -> None:
        nonlocal call_count
        call_count += 1
        if source == "ashby" and slug == "notion":
            raise RuntimeError("enqueue failed")
        return None

    runner._enqueue_crawl = mock_enqueue

    results = await runner.run_once()

    # All targets should still be attempted
    assert call_count == len(CRAWL_TARGETS)
    # The failed one should have an error result
    assert results.get("ashby:notion") == "error: enqueue failed"
    # Others should be enqueued
    assert results.get("greenhouse:stripe") == "enqueued"


@pytest.mark.asyncio
async def test_start_and_shutdown_are_idempotent():
    """start()/shutdown() should not error and should be callable twice."""
    runner = ScheduledCrawlRunner()

    runner.start()
    # Second start is a no-op (already started)
    runner.start()

    assert runner._scheduler is not None

    runner.shutdown()
    # Second shutdown is a no-op
    runner.shutdown()

    assert runner._scheduler is None
