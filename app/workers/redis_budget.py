"""Deterministic Upstash request-budget model for the ARQ worker.

Pure functions only — no Redis connections, no I/O. Used by tests and by
operators to answer "how many Redis requests does one idle worker burn?"
without guessing.

Model (ARQ 0.26.1, verified against installed ``arq/worker.py`` +
``arq/connections.py``):

* Every :meth:`Worker._poll_iteration` issues exactly one
  ``ZRANGEBYSCORE`` on the queue when the worker is idle
  (``allow_pick_jobs`` and spare ``max_jobs`` capacity). Iterations run every
  ``poll_delay`` seconds via ``poll(self.poll_delay_s)``.
* ``heart_beat()`` is a no-op except once per ``health_check_interval``
  (default 3600s), when ``record_health()`` issues ``ZCARD`` + ``PSETEX``.
* ``run_cron()`` issues nothing when no cron jobs are registered (our case).
* Worker startup issues one ``PING`` (``create_pool``) plus ``INFO`` x3 +
  ``DBSIZE`` (``log_redis_info``) — one-off, excluded from steady-state math.
"""

from __future__ import annotations

SECONDS_PER_DAY = 86400
DAYS_PER_MONTH = 30

IDLE_COMMANDS_PER_POLL = 1  # ZRANGEBYSCORE
HEALTH_CHECK_COMMANDS = 2  # ZCARD + PSETEX


def estimate_idle_requests_per_day(
    poll_delay_seconds: float,
    health_check_interval_seconds: float = 3600,
) -> float:
    """Steady-state Redis requests/day for one completely idle worker."""
    if poll_delay_seconds <= 0:
        raise ValueError("poll_delay_seconds must be positive")
    polls = SECONDS_PER_DAY / poll_delay_seconds
    health_runs = (
        SECONDS_PER_DAY / health_check_interval_seconds
        if health_check_interval_seconds and health_check_interval_seconds > 0
        else 0
    )
    return polls * IDLE_COMMANDS_PER_POLL + health_runs * HEALTH_CHECK_COMMANDS


def estimate_idle_requests_per_month(
    poll_delay_seconds: float,
    health_check_interval_seconds: float = 3600,
    days: int = DAYS_PER_MONTH,
) -> float:
    """Scale the daily idle estimate to a billing month."""
    return estimate_idle_requests_per_day(
        poll_delay_seconds, health_check_interval_seconds
    ) * days


def estimate_enqueue_requests(*, with_lock: bool = False) -> int:
    """Redis requests for one enqueue call (steady state, pool reused).

    Simple enqueue (``enqueue_job``): WATCH + EXISTS + PSETEX + ZADD = 4.
    Crawl enqueue adds the ``SET NX EX`` concurrency lock (+1 = 5).
    Excludes the one-off ``PING`` paid when a fresh pool is created — the
    dispatcher reuses a process-long-lived pool, so steady-state enqueues
    pay no PING.
    """
    return 5 if with_lock else 4


def estimate_job_execution_requests(*, records_crawl_status: bool = False) -> int:
    """Redis requests the worker pays to execute one job (ARQ internals).

    ``start_jobs`` pipeline (WATCH + EXISTS + ZSCORE + PSETEX) ~= 4,
    ``run_job`` pipeline (GET + INCR + EXPIRE) = 3,
    ``finish_job`` pipeline (SET result + ZREM x2 + DELETE) ~= 4-5.
    Crawl jobs add one ``SET EX`` crawl-status write.
    """
    return 12 if records_crawl_status else 11
