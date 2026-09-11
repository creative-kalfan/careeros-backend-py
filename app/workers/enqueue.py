"""Helper to enqueue ARQ jobs from FastAPI routes."""

from __future__ import annotations

import logging
from typing import Any, Optional

from arq.connections import ArqRedis

from app.config import get_settings
from app.workers.settings import get_redis_pool

settings = get_settings()

# TTL for the crawl lock (seconds). Must exceed the maximum expected crawl
# duration so a stale lock never permanently blocks a company.
CRAWL_LOCK_TTL_SECONDS = settings.crawl_lock_ttl_seconds

logger = logging.getLogger(__name__)


async def get_arq_redis() -> ArqRedis:
    # Shared process pool (see dispatcher._get_redis). Must NOT be aclosed
    # by callers.
    return await get_redis_pool()


async def enqueue_resume_parse(resume_id: str, user_id: str, storage_path: str) -> str:
    redis = await get_arq_redis()
    job = await redis.enqueue_job(
        "parse_resume_job",
        resume_id,
        user_id,
        storage_path,
    )
    if job is None:
        raise RuntimeError("Failed to enqueue parse_resume_job")
    return job.job_id


async def enqueue_crawl_company(source: str, slug: str) -> Optional[str]:
    """Enqueue a crawl job for a company, with a simple Redis concurrency lock.

    Returns the ARQ job_id if enqueued, or None if a crawl for the same
    company is already in progress.
    """
    redis = await get_arq_redis()
    lock_key = f"crawl_lock:{source}:{slug}"
    # SET NX EX: only set if not exists, with TTL
    acquired = await redis.set(lock_key, "1", ex=CRAWL_LOCK_TTL_SECONDS, nx=True)
    if not acquired:
        logger.info(
            "Crawl skipped: already in progress source=%s slug=%s lock=%s",
            source, slug, lock_key,
        )
        return None

    job = await redis.enqueue_job(
        "crawl_company_job",
        source,
        slug,
    )
    if job is None:
        raise RuntimeError("Failed to enqueue crawl_company_job")
    return job.job_id
