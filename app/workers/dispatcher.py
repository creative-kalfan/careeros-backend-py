"""Generic CareerOS background-job dispatcher.

The dispatcher is the only application code that should know about ARQ/Redis
connection details. All enqueue operations go through this thin layer.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from arq.connections import ArqRedis

from app.workers.registry import get_job_definition, get_registered_jobs
from app.workers.settings import get_redis_pool

logger = logging.getLogger(__name__)


async def _get_redis() -> ArqRedis:
    # Reuse the process-long-lived ARQ pool. Creating a new pool per enqueue
    # costs an extra PING plus a TLS handshake against the managed backend and churns
    # connections under scheduler bursts (14 back-to-back enqueues). The pool
    # is owned of app.workers.settings and lives for the process lifetime —
    # callers must NOT aclose() it.
    return await get_redis_pool()


async def enqueue(
    job_name: str,
    *args: Any,
    _defer_until: Optional[Any] = None,
    timeout: Optional[int] = None,
    _defer: Optional[int] = None,
) -> Optional[str]:
    """Enqueue a CareerOS background job.

    Args:
        job_name: Registered job name (see ``app.workers.registry``).
        *args: Positional payload arguments forwarded to the job callable.
        _defer_until: Schedule the job to run after a given UNIX timestamp.
        timeout: Override the default timeout for this enqueue (seconds).
        _defer: Defer execution by N seconds (passed to ARQ as ``_defer_by``).

    Returns:
        The ARQ ``job_id`` string, or ``None`` if enqueue failed.

    Raises:
        KeyError: If *job_name* is not registered.
    """
    get_job_definition(job_name)  # validate job_name exists
    redis = await _get_redis()
    job_kwargs: dict[str, Any] = {}
    if _defer_until is not None:
        job_kwargs["_defer_until"] = _defer_until
    if _defer is not None:
        job_kwargs["_defer_by"] = _defer
    if timeout is not None:
        job_kwargs["timeout"] = timeout

    job = await redis.enqueue_job(job_name, *args, **job_kwargs)
    if job is None:
        logger.error("Failed to enqueue job_name=%s", job_name)
        return None

    logger.info("Enqueued job_name=%s job_id=%s", job_name, job.job_id)
    return job.job_id


async def enqueue_resume_parse(resume_id: str, user_id: str, storage_path: str) -> Optional[str]:
    """Enqueue a resume-parsing job."""
    return await enqueue(
        "parse_resume_job",
        resume_id,
        user_id,
        storage_path,
    )


async def enqueue_crawl_company(
    source: str, slug: str, _defer: Optional[int] = None
) -> Optional[str]:
    """Enqueue a job-crawling job, with a simple Redis concurrency lock.

    Returns the ARQ job_id if enqueued, or None if a crawl for the same
    company is already in progress.
    """
    import uuid
    from app.config import get_settings as _get_settings
    settings = _get_settings()
    lock_ttl = settings.crawl_lock_ttl_seconds

    redis = await _get_redis()
    lock_key = f"crawl_lock:{source}:{slug}"
    job_id = str(uuid.uuid4())
    acquired = await redis.set(lock_key, job_id, ex=lock_ttl, nx=True)
    if not acquired:
        logger.info("Crawl skipped: already in progress source=%s slug=%s lock=%s", source, slug, lock_key)
        return None

    job_kwargs: dict[str, Any] = {}
    if _defer is not None and _defer > 0:
        job_kwargs["_defer_by"] = _defer
    job_kwargs["_job_id"] = job_id

    try:
        job = await redis.enqueue_job("crawl_company_job", source, slug, **job_kwargs)
        if job is None:
            logger.error("Failed to enqueue crawl_company_job source=%s slug=%s", source, slug)
            await redis.delete(lock_key)
            return None
        return job.job_id
    except Exception:
        try:
            owned_value = await redis.get(lock_key)
            if owned_value and owned_value.decode("utf-8") == job_id:
                await redis.delete(lock_key)
        except Exception:
            logger.warning("Failed to release crawl lock after enqueue error", exc_info=True)
        raise


async def enqueue_scheduled_crawl(source: str, slug: str, job_id: str) -> Optional[str]:
    """Enqueue DB-scheduled crawl; ARQ job ID is its deduplication key."""
    redis = await _get_redis()
    job = await redis.enqueue_job("crawl_company_job", source, slug, _job_id=job_id)
    if job is None:
        logger.info("Scheduled crawl deduplicated source=%s slug=%s", source, slug)
        return None
    return job.job_id
