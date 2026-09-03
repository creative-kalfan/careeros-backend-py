"""Generic CareerOS background-job dispatcher.

The dispatcher is the only application code that should know about ARQ/Redis
connection details. All enqueue operations go through this thin layer.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from arq.connections import ArqRedis, RedisSettings, create_pool

from app.config import get_settings
from app.workers.registry import get_job_definition, get_registered_jobs
from app.workers.settings import redis_settings

logger = logging.getLogger(__name__)


async def _get_redis() -> ArqRedis:
    return await create_pool(redis_settings)


async def enqueue(
    job_name: str,
    *args: Any,
    defer_until: Optional[Any] = None,
    timeout: Optional[int] = None,
    _defer: Optional[int] = None,
) -> Optional[str]:
    """Enqueue a CareerOS background job.

    Args:
        job_name: Registered job name (see ``app.workers.registry``).
        *args: Positional payload arguments forwarded to the job callable.
        defer_until: Schedule the job to run after a given UNIX timestamp.
        timeout: Override the default timeout for this enqueue (seconds).
        _defer: Defer execution by N seconds (ARQ ``defer`` parameter).

    Returns:
        The ARQ ``job_id`` string, or ``None`` if enqueue failed.

    Raises:
        KeyError: If *job_name* is not registered.
    """
    get_job_definition(job_name)  # validate job_name exists
    redis = await _get_redis()
    try:
        job_kwargs: dict[str, Any] = {}
        if defer_until is not None:
            job_kwargs["defer_until"] = defer_until
        if _defer is not None:
            job_kwargs["_defer"] = _defer
        if timeout is not None:
            job_kwargs["timeout"] = timeout

        job = await redis.enqueue_job(job_name, *args, **job_kwargs)
        if job is None:
            logger.error("Failed to enqueue job_name=%s", job_name)
            return None

        logger.info("Enqueued job_name=%s job_id=%s", job_name, job.job_id)
        return job.job_id
    finally:
        await redis.aclose()


async def enqueue_resume_parse(resume_id: str, user_id: str, storage_path: str) -> Optional[str]:
    """Enqueue a resume-parsing job."""
    return await enqueue(
        "parse_resume_job",
        resume_id,
        user_id,
        storage_path,
    )


async def enqueue_crawl_company(source: str, slug: str) -> Optional[str]:
    """Enqueue a job-crawling job, with a simple Redis concurrency lock.

    Returns the ARQ job_id if enqueued, or None if a crawl for the same
    company is already in progress.
    """
    from app.config import get_settings as _get_settings
    settings = _get_settings()
    lock_ttl = settings.crawl_lock_ttl_seconds

    redis = await _get_redis()
    try:
        lock_key = f"crawl_lock:{source}:{slug}"
        acquired = await redis.set(lock_key, "1", ex=lock_ttl, nx=True)
        if not acquired:
            logger.info("Crawl skipped: already in progress source=%s slug=%s lock=%s", source, slug, lock_key)
            return None

        job = await redis.enqueue_job("crawl_company_job", source, slug)
        if job is None:
            logger.error("Failed to enqueue crawl_company_job source=%s slug=%s", source, slug)
            return None
        return job.job_id
    finally:
        await redis.aclose()
