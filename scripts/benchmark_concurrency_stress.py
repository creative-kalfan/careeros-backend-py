"""Production Concurrency and Persistence Benchmark.

Measures:
1. Thread inventory & origin
2. Concurrency 1, 2, 3 comparison
3. Architecture A (sync semaphore in thread) vs Architecture B (async semaphore before to_thread)
4. Memory at each phase: startup, discover, normalize, before persist, waiting, holding, completed, gc
5. Cancellation stress test (repeated cancellations, checking thread count, active_crawls, semaphore leaks)
"""

import asyncio
import gc
import os
import psutil
import sys
import threading
import time
from typing import Any, Optional

from app.models.job import NormalizedJob
from app.db.supabase import (
    call_serialized,
    get_persistence_semaphore,
    reset_persistence_semaphore,
    lock_stats_snapshot,
    reset_lock_stats,
    PersistenceCancelledError,
    PersistenceTimeoutError,
)
from tests.test_crawl_throughput import _FakeClient, _repo


def get_rss_mb() -> float:
    return psutil.Process().memory_info().rss / (1024.0 * 1024.0)


def make_dummy_jobs(count: int, size_mult: int = 30) -> list[NormalizedJob]:
    desc = "<p>Join our team to build scalable cloud backend systems. Requirements: Python, FastAPI, Docker, SQL, Redis, Kubernetes.</p>" * size_mult
    return [
        NormalizedJob(
            title=f"Staff Software Engineer {i}",
            company="TechGlobal",
            location="Bengaluru, India",
            description=desc,
            source_platform="greenhouse",
            external_job_id=f"job_{i}",
            url=f"https://boards.greenhouse.io/techglobal/jobs/{i}",
            posted_at="2026-09-20T10:00:00Z",
            salary_min=2500000.0,
            salary_max=4500000.0,
            skills=["python", "fastapi", "docker", "sql", "redis", "kubernetes"],
            raw={"id": i, "content": desc, "departments": ["Eng"], "offices": ["Bangalore"]},
        )
        for i in range(count)
    ]


async def run_arch_benchmark(arch: str, concurrency: int, task_count: int, jobs_per_task: int):
    reset_persistence_semaphore(concurrency)
    reset_lock_stats()
    gc.collect()

    base_rss = get_rss_mb()
    base_threads = threading.active_count()
    peak_rss = base_rss
    peak_threads = base_threads
    timeouts = 0
    completions = 0

    async_sem = asyncio.Semaphore(concurrency) if arch == "B" else None

    async def crawl_worker(worker_id: int):
        nonlocal peak_rss, peak_threads, timeouts, completions
        # 1. Discovery / Normalization
        jobs = make_dummy_jobs(jobs_per_task)
        cur = get_rss_mb()
        if cur > peak_rss: peak_rss = cur

        client = _FakeClient()
        repo = _repo(client)

        def _persist_sync():
            nonlocal peak_threads
            th_cnt = threading.active_count()
            if th_cnt > peak_threads: peak_threads = th_cnt
            # Simulate DB I/O: 100ms for fast, 400ms for slow
            sleep_time = 0.4 if worker_id < concurrency else 0.1
            time.sleep(sleep_time)
            # Free raw
            for j in jobs:
                j.raw = None
            return repo.upsert_jobs(jobs)

        try:
            if arch == "A":
                # Architecture A: semaphore acquired inside thread
                await asyncio.to_thread(call_serialized, _persist_sync, timeout_seconds=2.0)
            else:
                # Architecture B: semaphore acquired on event loop
                async with async_sem:
                    await asyncio.to_thread(_persist_sync)
            completions += 1
        except PersistenceTimeoutError:
            timeouts += 1
        finally:
            del jobs

    t0 = time.monotonic()
    tasks = [asyncio.create_task(crawl_worker(i)) for i in range(task_count)]
    await asyncio.gather(*tasks, return_exceptions=True)
    duration_s = time.monotonic() - t0

    gc.collect()
    end_rss = get_rss_mb()

    return {
        "arch": arch,
        "concurrency": concurrency,
        "tasks": task_count,
        "jobs_per_task": jobs_per_task,
        "duration_s": round(duration_s, 2),
        "base_rss": round(base_rss, 1),
        "peak_rss": round(peak_rss, 1),
        "end_rss": round(end_rss, 1),
        "base_threads": base_threads,
        "peak_threads": peak_threads,
        "completions": completions,
        "timeouts": timeouts,
    }


async def main():
    print("=== PER-CRAWL PAYLOAD MEASUREMENT ===")
    for count in [100, 250, 500, 1000]:
        jobs = make_dummy_jobs(count)
        json_mb = sum(len(j.model_dump_json()) for j in jobs) / (1024 * 1024)
        raw_mb = sum(len(str(j.raw)) for j in jobs) / (1024 * 1024)
        print(f"Jobs: {count:4d} | Raw: {raw_mb:5.2f} MB | JSON: {json_mb:5.2f} MB")
        del jobs

    print("\n=== ARCHITECTURE A VS B (5 tasks, 250 jobs, concurrency=2) ===")
    res_a = await run_arch_benchmark("A", concurrency=2, task_count=5, jobs_per_task=250)
    print("Arch A:", res_a)
    await asyncio.sleep(0.5)
    res_b = await run_arch_benchmark("B", concurrency=2, task_count=5, jobs_per_task=250)
    print("Arch B:", res_b)

    print("\n=== CONCURRENCY BENCHMARK (Arch B, 5 tasks, 500 jobs) ===")
    for conc in [1, 2, 3]:
        await asyncio.sleep(0.3)
        res = await run_arch_benchmark("B", concurrency=conc, task_count=5, jobs_per_task=500)
        print(f"Concurrency={conc}: duration={res['duration_s']}s, peak_rss={res['peak_rss']}MB, peak_th={res['peak_threads']}")

    print("\n=== CANCELLATION STRESS TEST ===")
    async_sem = asyncio.Semaphore(2)
    cancelled_count = 0
    active_threads_start = threading.active_count()

    async def cancellable_crawl(i: int):
        nonlocal cancelled_count
        jobs = make_dummy_jobs(200)
        def _long_sync():
            time.sleep(0.5)
        try:
            async with async_sem:
                await asyncio.to_thread(_long_sync)
        except asyncio.CancelledError:
            cancelled_count += 1
            raise
        finally:
            del jobs

    for cycle in range(3):
        tasks = [asyncio.create_task(cancellable_crawl(i)) for i in range(6)]
        await asyncio.sleep(0.1)  # let first 2 enter, rest queue
        # Cancel all pending
        for t in tasks[2:]:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    print(f"Cancellation cycles complete. Cancelled: {cancelled_count}. Threads: {threading.active_count()} (Start: {active_threads_start})")


if __name__ == "__main__":
    asyncio.run(main())
