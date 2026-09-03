"""Scheduled crawl runner: enqueues per-source crawl jobs on a schedule.

Cadence is provider-specific and configurable via env:

    YC (priority 1):          YC_CRAWL_INTERVAL_HOURS          (default 24h)
    Firecrawl (priority 2):   FIRECRAWL_CRAWL_INTERVAL_HOURS   (default 24h)
    ATS boards (priority 3):  ATS_CRAWL_INTERVAL_HOURS         (default 24h)
    Aggregator (priority 4):  AGGREGATOR_CRAWL_INTERVAL_HOURS  (default 24h)
    Legacy override:          CRAWL_INTERVAL_HOURS (wins over all the above)

Targets come from ``app.crawlers.crawl_registry`` — add companies there, not
here. Provider enable flags: JOB_CRAWL_ENABLED (master), YC_CRAWL_ENABLED,
FIRECRAWL_ENABLED.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.crawlers.crawl_registry import all_targets, targets_for_provider
from app.services.jobs.job_ingestion_service import JobIngestionService

logger = logging.getLogger(__name__)

# Legacy default kept for backwards compatibility (used by main.py import).
DEFAULT_INTERVAL_HOURS = 6

# Backwards-compatible flat view of the registry for existing consumers/tests.
CRAWL_TARGETS: list[tuple[str, str]] = [(t.source, t.slug) for t in all_targets()]

# Provider family -> (enabled attr, interval attr) on Settings.
_PROVIDER_CONFIG = {
    "yc": ("yc_crawl_enabled", "yc_crawl_interval_hours"),
    "firecrawl": ("firecrawl_enabled", "firecrawl_crawl_interval_hours"),
    "ats": (None, "ats_crawl_interval_hours"),
    "aggregator": (None, "aggregator_crawl_interval_hours"),
}


class ScheduledCrawlRunner:
    """Owns the APScheduler instance and the recurring crawl enqueue pass."""

    def __init__(
        self,
        ingestion_service: Optional[JobIngestionService] = None,
        interval_hours: int = DEFAULT_INTERVAL_HOURS,
        enqueue_fn: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ) -> None:
        self.ingestion_service = ingestion_service or JobIngestionService()
        self.interval_hours = interval_hours
        self._enqueue_fn = enqueue_fn
        self._scheduler: Optional[AsyncIOScheduler] = None

    async def _enqueue_crawl(self, source: str, slug: str) -> None:
        """Enqueue a single crawl job via the ARQ dispatcher (Redis-locked)."""
        if self._enqueue_fn is not None:
            await self._enqueue_fn(source, slug)
            return
        from app.workers.dispatcher import enqueue_crawl_company

        job_id = await enqueue_crawl_company(source, slug)
        if job_id is None:
            raise RuntimeError(f"dispatcher returned no job id for {source}:{slug}")

    async def run_once(self) -> dict[str, str]:
        """Enqueue one crawl job per enabled target; failures are isolated."""
        targets = self._enabled_targets()
        logger.info("Scheduled crawl: enqueueing %d crawl targets", len(targets))
        results: dict[str, str] = {}
        for source, slug in targets:
            key = f"{source}:{slug}"
            try:
                await self._enqueue_crawl(source, slug)
                results[key] = "enqueued"
            except Exception as exc:
                logger.warning("Scheduled crawl: enqueue failed for %s: %s", key, exc)
                results[key] = f"error: {exc}"
        return results

    def _enabled_targets(self) -> list[tuple[str, str]]:
        """Registry targets filtered by provider enable flags from settings."""
        from app.config import get_settings

        settings = get_settings()
        if not settings.job_crawl_enabled:
            return []
        out: list[tuple[str, str]] = []
        for target in all_targets():
            cfg = _PROVIDER_CONFIG.get(target.provider)
            if cfg and cfg[0] is not None and not getattr(settings, cfg[0]):
                continue
            out.append((target.source, target.slug))
        return out

    async def run_provider_pass(self, provider: str) -> dict[str, str]:
        """Enqueue crawl jobs for one provider family (e.g. 'yc', 'firecrawl')."""
        enabled = set(self._enabled_targets())
        targets = [
            (t.source, t.slug) for t in targets_for_provider(provider)
            if (t.source, t.slug) in enabled
        ]
        logger.info("Scheduled crawl pass (%s): enqueueing %d targets", provider, len(targets))
        results: dict[str, str] = {}
        for source, slug in targets:
            key = f"{source}:{slug}"
            try:
                await self._enqueue_crawl(source, slug)
                results[key] = "enqueued"
            except Exception as exc:
                logger.warning(
                    "Scheduled crawl pass (%s): enqueue failed for %s: %s", provider, key, exc
                )
                results[key] = f"error: {exc}"
        return results

    def _interval_for(self, provider: str) -> float:
        """Resolve the effective interval (hours) for a provider family."""
        if self.interval_hours is not None:
            return self.interval_hours
        from app.config import get_settings

        settings = get_settings()
        if settings.crawl_interval_hours is not None:
            return settings.crawl_interval_hours
        return float(getattr(settings, _PROVIDER_CONFIG[provider][1]))

    def start(self) -> None:
        """Start the background scheduler (idempotent).

        One APScheduler job per provider family so each cadence is independent:
        a slow Firecrawl pass never delays YC discovery.
        """
        if self._scheduler is not None:
            return
        from app.config import get_settings

        settings = get_settings()
        if not settings.job_crawl_enabled:
            logger.info("Scheduled crawl runner disabled (JOB_CRAWL_ENABLED=false)")
            return

        self._scheduler = AsyncIOScheduler()
        for provider in _PROVIDER_CONFIG:
            if not targets_for_provider(provider):
                continue
            cfg = _PROVIDER_CONFIG[provider]
            if cfg[0] is not None and not getattr(settings, cfg[0]):
                logger.info("Scheduled crawl: provider %s disabled", provider)
                continue
            hours = self._interval_for(provider)
            self._scheduler.add_job(
                self.run_provider_pass,
                trigger=IntervalTrigger(hours=hours),
                args=[provider],
                id=f"scheduled_crawl_{provider}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                "Scheduled crawl: %s pass every %s hours (%d targets)",
                provider, hours, len(targets_for_provider(provider)),
            )
        self._scheduler.start()

    def shutdown(self) -> None:
        """Stop the background scheduler (idempotent)."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("ScheduledCrawlRunner stopped")