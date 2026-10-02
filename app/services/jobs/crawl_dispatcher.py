"""Durable, database-backed scheduling for registered crawl targets."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.db.supabase import get_service_client

logger = logging.getLogger(__name__)
_migration_available: bool | None = None
_migration_probed_at: float = 0.0


def adaptive_interval_minutes(
    current: int, *, changed: bool, unchanged_streak: int, priority: int,
    minimum: int = 360, maximum: int = 2880,
) -> int:
    """Return bounded cadence; P0 targets remain at most daily."""
    if changed:
        value = max(minimum, current // 2)
    elif unchanged_streak >= 3:
        value = min(maximum, max(current, minimum) * 2)
    else:
        value = current
    if priority == 0:
        value = min(value, 1440)
    return max(1, value)


def deterministic_job_id(source: str, slug: str, next_run_at: str) -> str:
    stamp = next_run_at.replace(":", "").replace("-", "").replace("+", "")
    digest = hashlib.sha1(f"{source}:{slug}:{stamp}".encode()).hexdigest()[:12]
    safe_slug = "".join(ch if ch.isalnum() else "-" for ch in slug.lower()).strip("-")[:40]
    return f"crawl:{source}:{safe_slug}:{digest}"


def _rpc(name: str, params: dict[str, Any]) -> Any:
    return get_service_client().rpc(name, params).execute().data


def _reset_migration_probe() -> None:
    """Clear the cached migration probe result so the next check re-probes."""
    global _migration_available, _migration_probed_at
    _migration_available = None
    _migration_probed_at = 0.0


def _migration_probe() -> bool:
    """Report whether the crawl_targets table (migration 025) is usable.

    The result is cached, but re-probed once it is older than
    ``settings.migration_probe_recheck_seconds`` so that applying migration 025
    after a deploy restores dispatch without a process restart. A cached value of
    ``None`` always forces a fresh probe.
    """
    global _migration_available, _migration_probed_at

    recheck = max(int(get_settings().migration_probe_recheck_seconds), 0)
    fresh = _migration_available is not None and (time.monotonic() - _migration_probed_at) < recheck
    if fresh:
        if not _migration_available:
            logger.critical(
                "crawl_targets migration 025 is still unavailable; DB crawl dispatch is "
                "DISABLED (no crawl targets will be dispatched). Apply migration 025 to "
                "restore dispatch; the probe retries every %ss.",
                recheck,
            )
        return _migration_available

    previously_available = _migration_available
    try:
        get_service_client().table("crawl_targets").select("id").limit(0).execute()
        _migration_available = True
    except Exception as exc:
        _migration_available = False
        logger.critical(
            "crawl_targets migration 025 is unavailable; DB crawl dispatch is DISABLED "
            "(no crawl targets will be dispatched, error=%s). Apply migration 025; the "
            "probe retries every %ss.",
            type(exc).__name__,
            recheck,
        )
    _migration_probed_at = time.monotonic()

    if _migration_available and previously_available is False:
        logger.warning(
            "crawl_targets migration 025 is now available; DB crawl dispatch is re-enabled "
            "without a restart."
        )
    return _migration_available


async def _post_webhook(url: str, payload: dict[str, Any] | None = None) -> None:
    def post() -> None:
        data = json.dumps(payload or {}).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5):
            pass
    try:
        await asyncio.to_thread(post)
    except Exception:
        logger.warning("crawl webhook request failed", exc_info=True)


async def check_crawl_slo() -> dict[str, int]:
    settings = get_settings()
    try:
        rows = await asyncio.to_thread(
            lambda: get_service_client().table("crawl_targets").select(
                "source,slug,next_run_at,last_success_at,created_at"
            ).eq("status", "active").execute().data or []
        )
    except Exception as exc:
        logger.warning("crawl SLO query unavailable (%s)", type(exc).__name__)
        return {"overdue": 0, "no_success_36h": 0}
    now = datetime.now(timezone.utc)
    overdue = no_success = 0
    for row in rows:
        due = _parse_dt(row.get("next_run_at"))
        success = _parse_dt(row.get("last_success_at"))
        created = _parse_dt(row.get("created_at"))
        overdue += int(due is not None and (now - due).total_seconds() > settings.slo_overdue_minutes * 60)
        reference = success or created
        no_success += int(reference is not None and (now - reference).total_seconds() > 36 * 3600)
    if overdue or no_success:
        message = f"Crawl SLO breached: overdue={overdue} no_success_36h={no_success}"
        try:
            import sentry_sdk
            sentry_sdk.capture_message(message, level="error")
        except Exception:
            logger.error(message)
        if settings.alert_webhook_url:
            await _post_webhook(settings.alert_webhook_url, {"message": message})
    return {"overdue": overdue, "no_success_36h": no_success}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


# crawl_company_job is registered with timeout=300 (app/workers/jobs/crawl_jobs.py).
_CRAWL_JOB_TIMEOUT_SECONDS = 300


def _crawl_job_timeout_seconds() -> int:
    try:
        from app.workers.registry import get_job_definition

        return int(get_job_definition("crawl_company_job").timeout)
    except Exception:
        return _CRAWL_JOB_TIMEOUT_SECONDS


def _worker_capacity() -> int:
    """Return the ARQ worker's real ``max_jobs``.

    ARQ injects only ``ctx['redis']`` (arq/worker.py:356); there is no
    ``ctx['worker']``, so capacity must come from WorkerSettings. Imported
    lazily because app.workers.settings reaches this module through
    app.workers.jobs.crawl_jobs.
    """
    try:
        from app.workers.settings import WorkerSettings

        return max(1, int(getattr(WorkerSettings, "max_jobs", 1)))
    except Exception:
        return max(1, int(get_settings().persistence_max_concurrency))


async def _queue_depth() -> int | None:
    """Return ARQ queue depth (waiting + running), or None when unknown.

    ponytail: one ZCARD per dispatch tick only -- no continuous sampling, so a
    burst between ticks is not observed. Depth is an upper bound on in-flight
    work (ARQ only removes on finish), which is the safe direction for a guard.
    """
    try:
        from app.workers.dispatcher import _get_redis

        redis = await _get_redis()
        return int(await redis.zcard(redis.default_queue_name))
    except Exception as exc:
        logger.warning("crawl queue depth unavailable (%s)", type(exc).__name__)
        return None


def _check_lease_coverage(settings: Any, capacity: int) -> None:
    """Warn when the lease cannot outlive the worst-case queue wait.

    The admission guard below only admits while depth < capacity, so at most
    ``capacity`` jobs are ever ahead of a newly claimed one and every one of
    them completes within a single job timeout. Worst-case wait is therefore one
    job timeout. A lease at or below that lets the next tick re-claim the same
    still-queued target.
    """
    timeout = _crawl_job_timeout_seconds()
    worst_case_wait = timeout
    if settings.crawl_lease_seconds <= worst_case_wait:
        logger.warning(
            "crawl lease does not cover worst-case queue wait: lease=%ss <= "
            "worst_case_wait=%ss (capacity=%s x timeout=%ss). Targets can be "
            "re-claimed while still queued, causing double dispatch.",
            settings.crawl_lease_seconds,
            worst_case_wait,
            capacity,
            timeout,
        )


async def dispatch_due_targets(ctx: dict[str, Any]) -> int:
    """Claim and enqueue one bounded batch; leases recover crashed dispatchers."""
    if not _migration_probe():
        return 0
    settings = get_settings()
    capacity = _worker_capacity()
    _check_lease_coverage(settings, capacity)
    depth = await _queue_depth()
    if depth is None:
        limit = max(1, min(settings.dispatch_batch, capacity))
        logger.warning(
            "crawl queue depth unknown; admission guard DEGRADED to capacity=%s only "
            "(no backpressure on a backed-up queue).",
            capacity,
        )
    else:
        free = capacity - depth
        if free <= 0:
            logger.info(
                "crawl admission backpressure: queue_depth=%s >= capacity=%s; claiming nothing.",
                depth,
                capacity,
            )
            return 0
        limit = max(1, min(settings.dispatch_batch, free))
    try:
        rows = await asyncio.to_thread(_rpc, "claim_due_crawl_targets", {
            "p_limit": limit, "p_lease_seconds": settings.crawl_lease_seconds,
        })
    except Exception as exc:
        logger.warning("crawl target claim failed (%s)", type(exc).__name__)
        return 0

    from app.workers.dispatcher import enqueue_scheduled_crawl
    enqueued = 0
    for row in rows or []:
        source, slug = row["source"], row.get("slug") or ""
        run_id = deterministic_job_id(source, slug, str(row.get("next_run_at", "")))
        try:
            job_id = await enqueue_scheduled_crawl(source, slug, run_id)
            if job_id:
                enqueued += 1
            else:
                await complete_target(source, slug, False, error="ARQ duplicate or enqueue rejected")
        except Exception as exc:
            logger.warning("crawl enqueue failed source=%s slug=%s (%s)", source, slug, type(exc).__name__)
            await complete_target(source, slug, False, error=type(exc).__name__)
    return enqueued


async def complete_target(
    source: str, slug: str, success: bool, *, job_count: int = 0,
    content_hash: str | None = None, error: str | None = None, not_found: bool = False,
) -> None:
    # Only DB-dispatched workers mutate a leased target; manual/legacy jobs
    # remain on the old schedule until the migration probe succeeds.
    if _migration_available is not True:
        return
    settings = get_settings()
    priority = 1
    interval = settings.crawl_min_interval_minutes
    try:
        record = await asyncio.to_thread(
            lambda: get_service_client().table("crawl_targets").select(
                "priority,interval_minutes,hash_unchanged_streak,content_hash"
            ).eq("source", source).eq("slug", slug).limit(1).execute().data
        )
        if record:
            priority = int(record[0].get("priority", 1))
            interval = adaptive_interval_minutes(
                int(record[0].get("interval_minutes", interval)),
                changed=content_hash is not None and content_hash != record[0].get("content_hash"),
                unchanged_streak=int(record[0].get("hash_unchanged_streak", 0)) + 1,
                priority=priority,
                minimum=settings.crawl_min_interval_minutes,
                maximum=settings.crawl_max_interval_minutes,
            )
        await asyncio.to_thread(_rpc, "complete_crawl_target", {
            "p_source": source, "p_slug": slug, "p_success": success,
            "p_interval_minutes": interval, "p_job_count": job_count,
            "p_content_hash": content_hash, "p_error": error, "p_not_found": not_found,
            "p_min_interval_minutes": settings.crawl_min_interval_minutes,
            "p_max_interval_minutes": settings.crawl_max_interval_minutes,
            "p_dead_after_failures": settings.crawl_dead_after_failures,
        })
    except Exception as exc:
        logger.warning("crawl target completion unavailable (%s)", type(exc).__name__)


async def dispatcher_loop(ctx: dict[str, Any]) -> None:
    """Run crawl dispatch and hourly SLO/heartbeat checks until cancelled."""
    settings = get_settings()
    last_slo = 0.0
    last_discovery_date = ""
    while True:
        await dispatch_due_targets(ctx)
        now = asyncio.get_running_loop().time()
        if now - last_slo >= 3600:
            await check_crawl_slo()
            last_slo = now
        date_key = datetime.now(timezone.utc).date().isoformat()
        if date_key != last_discovery_date:
            try:
                from app.workers.dispatcher import _get_redis
                redis = await _get_redis()
                await redis.enqueue_job("discover_ats_targets", _job_id=f"discover-ats:{date_key}")
                last_discovery_date = date_key
            except Exception as exc:
                logger.warning("ATS discovery enqueue failed (%s)", type(exc).__name__)
        if settings.heartbeat_url:
            await _post_webhook(settings.heartbeat_url)
        await asyncio.sleep(max(5, settings.dispatch_tick_seconds))
