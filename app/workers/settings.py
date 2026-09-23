"""ARQ worker settings for CareerOS."""

from __future__ import annotations

import logging
from typing import Any

from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.worker import Worker, check_health, func, run_worker

from app.config import get_settings
from app.workers import functions
from app.workers.jobs.crawl_jobs import crawl_company_job
from app.workers.jobs.interview_prep_jobs import generate_interview_prep_job  # noqa: F401 — registration side effect
from app.workers.jobs.job_intelligence_job import analyze_job_intelligence_job
from app.workers.registry import JobDefinition, get_registered_jobs

logger = logging.getLogger(__name__)

_settings = get_settings()

# Strong reference: keeps the APScheduler instance (and its event-loop
# handles) alive for the worker process lifetime. Without this the scheduler
# could be garbage-collected after startup.
_crawl_runner = None


def normalize_redis_dsn(dsn: str) -> str:
    """Map Aiven Valkey URI schemes to the redis-py equivalents.

    Aiven Console hands out ``valkey://`` / ``valkeys://`` URIs; neither
    ARQ's ``RedisSettings.from_dsn`` nor ``redis.asyncio.from_url`` accepts
    those schemes (both expect ``redis://`` / ``rediss://``). The wire
    protocol is identical, so this is a prefix rewrite only — host, auth,
    port, and db are untouched. Pass-through for everything else.
    """
    if dsn.startswith("valkeys://"):
        return "rediss://" + dsn[len("valkeys://"):]
    if dsn.startswith("valkey://"):
        return "redis://" + dsn[len("valkey://"):]
    return dsn


redis_settings = RedisSettings.from_dsn(normalize_redis_dsn(_settings.redis_url))

redis_pool: ArqRedis | None = None


async def get_redis_pool() -> ArqRedis:
    global redis_pool
    if redis_pool is None:
        redis_pool = await create_pool(redis_settings)
    return redis_pool


def _build_function_list() -> list[Any]:
    """Build the ARQ function list from the CareerOS job registry."""
    fn_list = []
    for job_def in get_registered_jobs():
        fn_list.append(
            func(
                job_def.callable,
                name=job_def.name,
                max_tries=job_def.max_tries,
                timeout=job_def.timeout,
            )
        )
    return fn_list


async def worker_startup(ctx: dict[str, Any]) -> None:
    """ARQ on_startup: own the crawler scheduler in the worker process."""
    global _crawl_runner
    settings = get_settings()
    logger.info(
        "crawler scheduler initialization started crawler_enabled=%s",
        str(settings.job_crawl_enabled).lower(),
    )
    if not settings.job_crawl_enabled:
        logger.info("crawler scheduler disabled (JOB_CRAWL_ENABLED=false)")
        return
    try:
        from app.services.jobs.scheduled_crawl_runner import ScheduledCrawlRunner

        _crawl_runner = ScheduledCrawlRunner()
        _crawl_runner.start()
        sched = _crawl_runner._scheduler
        jobs = sched.get_jobs() if sched is not None else []
        logger.info("crawler scheduler initialized jobs=%d", len(jobs))
        for job in jobs:
            logger.info(
                "next crawl scheduled id=%s next_run_time=%s",
                job.id,
                job.next_run_time.isoformat() if job.next_run_time else "none",
            )
        logger.info("crawler scheduler started")
    except Exception:
        # Worker must stay alive for API-enqueued jobs; scheduler failure is
        # observable via this log, never silent.
        logger.exception("crawler scheduler initialization failed")
        _crawl_runner = None


async def worker_shutdown(ctx: dict[str, Any]) -> None:
    """ARQ on_shutdown: stop the crawler scheduler (idempotent)."""
    global _crawl_runner
    if _crawl_runner is not None:
        try:
            _crawl_runner.shutdown()
        except Exception:
            logger.exception("crawler scheduler shutdown failed")
        finally:
            _crawl_runner = None


class WorkerSettings:
    functions = _build_function_list()
    redis_settings = redis_settings
    on_startup = worker_startup
    on_shutdown = worker_shutdown
    job_timeout = 300
    keep_result = 3600
    max_jobs = 10
    # Queue-poll interval: env-driven (ARQ_POLL_DELAY_SECONDS, default 10s).
    # Idle cost is ~86400/poll_delay ZRANGEBYSCORE/day: 0.5s = ~172.8k/day
    # (~5.2M/month — too hot for metered/request-billed Redis plans);
    # 10s = ~8.6k/day, safe everywhere. On non-metered backends (e.g. Aiven
    # Valkey free tier) lower ARQ_POLL_DELAY_SECONDS via env for faster
    # pickup — no code change needed.
    # Health checks stay at the ARQ default (hourly: ZCARD + PSETEX, ~48
    # req/day, negligible) — do not shorten health_check_interval.
    poll_delay = _settings.arq_poll_delay_seconds
    health_check_interval = 3600
    retry_jobs = True
