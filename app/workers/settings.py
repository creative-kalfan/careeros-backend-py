"""ARQ worker settings for CareerOS."""

from __future__ import annotations

from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.worker import Worker, check_health, func, run_worker

from app.config import get_settings
from app.workers import functions
from app.workers.jobs.crawl_jobs import crawl_company_job
from app.workers.jobs.job_intelligence_job import analyze_job_intelligence_job
from app.workers.registry import JobDefinition, get_registered_jobs

_settings = get_settings()

redis_settings = RedisSettings.from_dsn(_settings.redis_url)

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


class WorkerSettings:
    functions = _build_function_list()
    redis_settings = redis_settings
    job_timeout = 300
    keep_result = 3600
    max_jobs = 10
    poll_delay = 0.5
    retry_jobs = True
