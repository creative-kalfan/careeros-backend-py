"""Background job for bounded retention pruning of crawl observability data."""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.repositories.observability_repository import ObservabilityRepository
from app.workers.registry import WorkloadClass, register_job

logger = logging.getLogger(__name__)


@register_job(
    "prune_crawl_observability_job",
    timeout=120,
    max_tries=1,
    retry=False,
    description="Prune old crawl_runs and job_events based on retention policy (default 90 days).",
    workload_class=WorkloadClass.MAINTENANCE,
)
async def prune_crawl_observability_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """Prune crawl_runs and job_events older than CRAWL_OBSERVABILITY_RETENTION_DAYS.
    
    Never prunes jobs table rows. Bounded batch size.
    """
    settings = get_settings()
    retention_days = int(settings.crawl_observability_retention_days)
    logger.info("Starting crawl observability pruning (retention_days=%d)", retention_days)

    repo = ObservabilityRepository()
    if not repo.is_available():
        logger.info("Crawl observability tables not available; skipping pruning.")
        return {"status": "unavailable", "pruned_events": 0, "pruned_runs": 0}

    import asyncio
    result = await asyncio.to_thread(repo.prune_old_observability_data, retention_days=retention_days, batch_size=500)
    logger.info(
        "Crawl observability pruning complete: pruned_events=%d pruned_runs=%d",
        result.get("pruned_events", 0),
        result.get("pruned_runs", 0),
    )
    return {"status": "success", **result}
