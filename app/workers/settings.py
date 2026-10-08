"""ARQ worker settings for CareerOS."""

from __future__ import annotations

import logging
import asyncio
import os
from typing import Any

from arq import cron
from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.worker import Worker, check_health, func, run_worker

from app.config import get_settings
from app.workers.functions import aggregate_market_skill_trends_job
from app.workers.jobs.crawl_jobs import crawl_company_job
from app.workers.jobs.interview_prep_jobs import generate_interview_prep_job  # noqa: F401 — registration side effect
from app.workers.jobs.job_intelligence_job import analyze_job_intelligence_job, analyze_jobs_batch
from app.workers.jobs.observability_retention_job import prune_crawl_observability_job
from app.workers.jobs.embedding_jobs import embed_jobs_batch, backfill_job_embeddings  # noqa: F401 — registration side effect
from app.workers.registry import JobDefinition, get_registered_jobs

logger = logging.getLogger(__name__)

# Restrict glibc memory arenas on Linux (Render 512MB RAM ceiling)
# Prevents multi-threaded allocator fragmentation where 13 threads create 13+ arenas.
try:
    import ctypes
    libc = ctypes.CDLL("libc.so.6")
    libc.mallopt(-8, 2)  # M_ARENA_MAX = 2
except Exception:
    pass

_settings = get_settings()

# Strong reference: keeps the APScheduler instance (and its event-loop
# handles) alive for the worker process lifetime. Without this the scheduler
# could be garbage-collected after startup.
_crawl_runner = None
_dispatcher_task: asyncio.Task | None = None
_health_server: asyncio.Server | None = None
_analysis_worker: Worker | None = None
_analysis_worker_task: asyncio.Task | None = None


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


_redis_parsed = RedisSettings.from_dsn(normalize_redis_dsn(_settings.redis_url))
redis_settings = RedisSettings(**{
    **vars(_redis_parsed),
    "conn_timeout": max(1, int(_settings.arq_connect_timeout)),
    "conn_retries": 5,
    "conn_retry_delay": 1,
    "retry_on_timeout": True,
})

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
    """Start crawl dispatch and optional legacy/health services."""
    global _crawl_runner, _dispatcher_task, _health_server
    settings = get_settings()
    logger.info(
        "crawler scheduler initialization started crawler_enabled=%s",
        str(settings.job_crawl_enabled).lower(),
    )
    if not settings.job_crawl_enabled:
        logger.info("crawler scheduler disabled (JOB_CRAWL_ENABLED=false)")
    else:
        try:
            redis = ctx.get("redis")
            if redis is not None:
                policy = await redis.config_get("maxmemory-policy")
                value = policy.get("maxmemory-policy") if isinstance(policy, dict) else None
                if value and value != "noeviction":
                    logger.critical("Redis maxmemory-policy=%s; ARQ jobs may be evicted", value)
        except Exception as exc:
            logger.warning("Unable to inspect Redis maxmemory-policy: %s", exc)
    if settings.job_crawl_enabled and settings.crawl_scheduler_mode == "github":
        logger.info(
            "crawl scheduling delegated to external trigger (CRAWL_SCHEDULER_MODE=github); "
            "worker only consumes queued jobs"
        )
    elif settings.job_crawl_enabled and settings.legacy_apscheduler_enabled:
        try:
            from app.services.jobs.scheduled_crawl_runner import ScheduledCrawlRunner
            _crawl_runner = ScheduledCrawlRunner()
            _crawl_runner.start()
            logger.warning("legacy APScheduler enabled; possible duplicate scheduling")
        except Exception:
            logger.exception("legacy APScheduler initialization failed")
    elif settings.job_crawl_enabled:
        from app.services.jobs.crawl_dispatcher import dispatcher_loop
        _dispatcher_task = asyncio.create_task(dispatcher_loop(ctx), name="crawl-dispatcher")

    if settings.worker_consume_analysis_queue and settings.analysis_queue_name != getattr(WorkerSettings, "queue_name", "arq:queue"):
        try:
            analysis_funcs = [
                func(analyze_job_intelligence_job, name="analyze_job_intelligence", timeout=300, max_tries=2),
                func(analyze_jobs_batch, name="analyze_jobs_batch", timeout=300, max_tries=2),
            ]
            global _analysis_worker, _analysis_worker_task
            _analysis_worker = Worker(
                functions=analysis_funcs,
                queue_name=settings.analysis_queue_name,
                redis_pool=ctx.get("redis"),
                redis_settings=redis_settings,
                max_jobs=max(1, settings.persistence_max_concurrency),
                poll_delay=settings.arq_poll_delay,
                job_timeout=300,
                keep_result=5,
                retry_jobs=True,
            )
            _analysis_worker_task = asyncio.create_task(_analysis_worker.main(), name="analysis-worker")
            logger.info("analysis worker loop started queue=%s", settings.analysis_queue_name)
        except Exception as exc:
            logger.warning("Failed to start embedded analysis worker loop (%s)", exc)

    if settings.worker_http_health:
        async def health(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await reader.read(4096)
                body = b'{"status":"ok","service":"worker"}'
                headers = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n"
                writer.write(headers + body)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        try:
            _health_server = await asyncio.start_server(health, "0.0.0.0", int(os.getenv("PORT", "8000")))
        except Exception:
            logger.exception("worker health endpoint failed to start")


async def worker_shutdown(ctx: dict[str, Any]) -> None:
    """Stop scheduler, dispatcher, and optional health listener."""
    global _crawl_runner, _dispatcher_task, _health_server, _analysis_worker, _analysis_worker_task
    if _analysis_worker_task is not None:
        _analysis_worker_task.cancel()
        try:
            await _analysis_worker_task
        except asyncio.CancelledError:
            pass
        _analysis_worker_task = None
    if _analysis_worker is not None:
        try:
            await _analysis_worker.close()
        except Exception:
            pass
        _analysis_worker = None
    if _dispatcher_task is not None:
        _dispatcher_task.cancel()
        try:
            await _dispatcher_task
        except asyncio.CancelledError:
            pass
        _dispatcher_task = None
    if _health_server is not None:
        _health_server.close()
        await _health_server.wait_closed()
        _health_server = None
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
    keep_result = 5
    max_jobs = max(1, _settings.persistence_max_concurrency)
    poll_delay = _settings.arq_poll_delay
    health_check_interval = 3600
    retry_jobs = True
    cron_jobs = [
        cron(aggregate_market_skill_trends_job, hour=0, minute=0, run_at_startup=True),
        cron(prune_crawl_observability_job, hour=3, minute=0, run_at_startup=False),
    ]


class AnalysisWorkerSettings:
    """Dedicated worker configuration for intelligence analysis jobs.

    Run via: `arq app.workers.settings.AnalysisWorkerSettings`
    Consumes ONLY the analysis queue (env ANALYSIS_QUEUE_NAME, default 'arq:queue:analysis').
    When a dedicated analysis worker process is running, set
    `WORKER_CONSUME_ANALYSIS_QUEUE=false` on the crawl worker.
    """
    functions = [
        func(analyze_job_intelligence_job, name="analyze_job_intelligence", timeout=300, max_tries=2),
        func(analyze_jobs_batch, name="analyze_jobs_batch", timeout=300, max_tries=2),
    ]
    redis_settings = redis_settings
    queue_name = _settings.analysis_queue_name
    job_timeout = 300
    keep_result = 5
    max_jobs = max(1, _settings.persistence_max_concurrency)
    poll_delay = _settings.arq_poll_delay
    health_check_interval = 3600
    retry_jobs = True
