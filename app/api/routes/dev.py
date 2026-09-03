"""Development-only ARQ job enqueue endpoint.

NOT for production use — used to verify the ARQ pipeline during
infrastructure development phases.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.workers.functions import careeros_worker_health

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dev/arq", tags=["dev-arq"])


class EnqueueHealthResponse(BaseModel):
    success: bool
    job_id: str


class EnqueueCrawlResponse(BaseModel):
    success: bool
    job_id: Optional[str]
    source: str
    slug: str


class RedisHealthResponse(BaseModel):
    redis: str
    status: str


async def _get_arq_redis():
    from arq.connections import ArqRedis, RedisSettings, create_pool
    from app.workers.settings import redis_settings as worker_redis_settings

    pool = await create_pool(worker_redis_settings)
    return pool


@router.post("/enqueue/crawl/{source}/{slug}", response_model=EnqueueCrawlResponse)
async def enqueue_crawl_job(source: str, slug: str) -> EnqueueCrawlResponse:
    """Enqueue a single company crawl job into the ARQ queue (dev only)."""
    from app.workers.enqueue import enqueue_crawl_company

    job_id = await enqueue_crawl_company(source, slug)
    if job_id is None:
        logger.info("Crawl skipped (already in progress) source=%s slug=%s", source, slug)
        return EnqueueCrawlResponse(success=False, job_id=None, source=source, slug=slug)
    logger.info("Enqueued crawl job source=%s slug=%s job_id=%s", source, slug, job_id)
    return EnqueueCrawlResponse(success=True, job_id=job_id, source=source, slug=slug)


@router.get("/health/redis", response_model=RedisHealthResponse)
async def redis_health() -> RedisHealthResponse:
    """Check Redis connectivity without enqueuing a job."""
    redis = await _get_arq_redis()
    try:
        pong = await redis.ping()
        if pong:
            return RedisHealthResponse(redis="redis", status="ok")
        return RedisHealthResponse(redis="redis", status="unreachable")
    except Exception as exc:
        logger.error("Redis health check failed: %s", exc)
        raise HTTPException(status_code=503, detail="Redis unreachable") from exc
    finally:
        await redis.aclose()


@router.get("/crawl-status")
async def crawl_status() -> dict:
    """Last crawl run per registered target (observability).

    Reads the ``crawl_status:<source>:<slug>`` records written by the crawl
    worker after each run. Answers "when did this source last crawl
    successfully?" without a dedicated database table.
    """
    from app.crawlers.crawl_registry import all_targets
    from app.workers.settings import get_redis_pool

    redis = await get_redis_pool()
    out: dict[str, dict] = {}
    for target in all_targets():
        try:
            raw = await redis.get(f"crawl_status:{target.source}:{target.slug}")
        except Exception as exc:
            logger.warning("crawl-status read failed: %s", exc)
            raw = None
        out[target.key] = json.loads(raw) if raw else {"status": "unknown"}
    return {"success": True, "data": out}


@router.post("/enqueue/health", response_model=EnqueueHealthResponse)
async def enqueue_health_job() -> EnqueueHealthResponse:
    """Enqueue the health-check job into the ARQ queue."""
    redis = await _get_arq_redis()
    try:
        job = await redis.enqueue_job("careeros_worker_health")
        if job is None:
            raise HTTPException(status_code=500, detail="Failed to enqueue job")
        logger.info("Enqueued job %s", job.job_id)
        return EnqueueHealthResponse(success=True, job_id=job.job_id)
    finally:
        await redis.aclose()

