"""Scheduled crawl runner: runs job ingestion on a recurring schedule.

Uses APScheduler's AsyncIOScheduler so ingestion runs unattended in the
background while the FastAPI server is up. Each run is isolated per-source so
a single crawler failure does not abort the whole batch, and existing jobs are
never destroyed by a transient failure.
"""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.services.jobs.job_ingestion_service import JobIngestionService

logger = logging.getLogger(__name__)

# Default: run every 6 hours. Overridable via env var CRAWL_INTERVAL_HOURS.
DEFAULT_INTERVAL_HOURS = 6


class ScheduledCrawlRunner:
    """Owns the APScheduler instance and the recurring ingestion job."""

    def __init__(
        self,
        ingestion_service: Optional[JobIngestionService] = None,
        interval_hours: int = DEFAULT_INTERVAL_HOURS,
    ) -> None:
        self.ingestion_service = ingestion_service or JobIngestionService()
        self.interval_hours = interval_hours
        self._scheduler: Optional[AsyncIOScheduler] = None

    async def run_once(self) -> dict[str, dict[str, int]]:
        """Run a single full ingestion pass (all sources, isolated)."""
        logger.info("Scheduled crawl: starting ingestion pass")
        try:
            results = await self.ingestion_service.ingest_all()
            logger.info("Scheduled crawl: ingestion pass complete: %s", results)
            return results
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Scheduled crawl: ingestion pass failed: %s", exc)
            return {}

    def start(self) -> None:
        """Start the background scheduler (idempotent)."""
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.run_once,
            trigger=IntervalTrigger(hours=self.interval_hours),
            id="scheduled_crawl",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info(
            "ScheduledCrawlRunner started (every %s hours)", self.interval_hours
        )

    def shutdown(self) -> None:
        """Stop the background scheduler (idempotent)."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("ScheduledCrawlRunner stopped")