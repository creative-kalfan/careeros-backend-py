"""Tests for the scheduled crawl runner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.jobs.scheduled_crawl_runner import ScheduledCrawlRunner


@pytest.mark.asyncio
async def test_run_once_calls_ingest_all():
    """run_once should invoke the ingestion service's ingest_all."""
    runner = ScheduledCrawlRunner()
    runner.ingestion_service = MagicMock()
    runner.ingestion_service.ingest_all = AsyncMock(
        return_value={"ashby": {"inserted": 1, "updated": 0}}
    )

    results = await runner.run_once()

    runner.ingestion_service.ingest_all.assert_awaited_once()
    assert results == {"ashby": {"inserted": 1, "updated": 0}}


@pytest.mark.asyncio
async def test_run_once_handles_ingestion_failure():
    """A failure in ingest_all should not raise; it returns an empty dict."""
    runner = ScheduledCrawlRunner()
    runner.ingestion_service = MagicMock()
    runner.ingestion_service.ingest_all = AsyncMock(side_effect=RuntimeError("boom"))

    results = await runner.run_once()

    assert results == {}


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
