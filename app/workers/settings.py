"""ARQ worker settings for CareerOS."""

from __future__ import annotations

from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.worker import Worker, check_health, func, run_worker

from app.config import get_settings
from app.workers import functions
from app.workers.jobs.crawl_jobs import crawl_company_job
from app.workers.jobs.interview_prep_jobs import generate_interview_prep_job  # noqa: F401 — registration side effect
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
    # Queue-poll interval: env-driven (ARQ_POLL_DELAY_SECONDS, default 10s).
    # Idle cost is ~86400/poll_delay ZRANGEBYSCORE/day: 0.5s = ~172.8k/day
    # (~5.2M/month, >10x the 500k Upstash budget); 10s = ~8.6k/day
    # (~259k/month, ~52% of budget). Job pickup latency grows with the
    # interval (p99 ~= poll_delay); 10s is the cheapest value that keeps
    # interactive resume-parse pickup acceptable while fitting the budget.
    # Health checks stay at the ARQ default (hourly: ZCARD + PSETEX, ~48
    # req/day, negligible) — do not shorten health_check_interval.
    poll_delay = _settings.arq_poll_delay_seconds
    health_check_interval = 3600
    retry_jobs = True
