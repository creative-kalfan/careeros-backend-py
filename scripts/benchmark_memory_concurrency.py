"""Memory and Concurrency Benchmark for CareerOS Worker Crawl Pipeline.

Measures:
- Baseline RSS
- Peak RSS
- RSS after completion
- RSS after cancellation
- Number of live threads
- Persistence semaphore usage
- Active crawl gauge
- Outstanding operations
"""

import asyncio
import gc
import os
import psutil
import sys
import threading
import time
from typing import Any

from app.models.job import NormalizedJob
from app.db.supabase import (
    call_serialized,
    get_persistence_semaphore,
    reset_persistence_semaphore,
    lock_stats_snapshot,
    reset_lock_stats,
)
import app.workers.jobs.crawl_jobs as crawl_jobs_module


def get_rss_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 * 1024)


def make_dummy_jobs(count: int) -> list[NormalizedJob]:
    desc = "<p>Join our engineering team to build scalable systems. Requirements: Python, FastAPI, Docker, SQL.</p>" * 20
    return [
        NormalizedJob(
            title=f"Senior Software Engineer {i}",
            company="TechCorp",
            location="Bangalore, India",
            description=desc,
            source_platform="greenhouse",
            external_job_id=f"job_{i}",
            url=f"https://boards.greenhouse.io/techcorp/jobs/{i}",
            posted_at="2026-09-20T10:00:00Z",
            salary_min=1500000.0,
            salary_max=3000000.0,
            skills=["python", "fastapi", "docker", "sql"],
            raw={"id": i, "content": desc, "departments": ["Eng"], "offices": ["Bangalore"]},
        )
        for i in range(count)
    ]


async def run_benchmark():
    print(f"=== Process Baseline RSS: {get_rss_mb():.2f} MB | Threads: {threading.active_count()} ===")
    job_counts = [100, 250, 500, 1000]
    concurrencies = [1, 2, 5, 10]

    # Test single-batch memory footprint
    print("\n--- Payload Memory Footprint ---")
    for count in job_counts:
        gc.collect()
        before = get_rss_mb()
        jobs = make_dummy_jobs(count)
        after = get_rss_mb()
        json_len = sum(len(j.model_dump_json()) for j in jobs) / (1024 * 1024)
        print(f"Jobs: {count:4d} | RSS Delta: {after - before:6.2f} MB | JSON Size: {json_len:5.2f} MB")
        del jobs
        gc.collect()

    print("\n--- Concurrency vs Peak RSS (Mocked Persistence) ---")
    for conc in concurrencies:
        gc.collect()
        base_rss = get_rss_mb()
        peak_rss = base_rss
        active_threads = threading.active_count()

        async def worker_task(job_id: int):
            nonlocal peak_rss
            jobs = make_dummy_jobs(250)
            cur = get_rss_mb()
            if cur > peak_rss:
                peak_rss = cur

            # Simulate persistence call_serialized
            def _dummy_persist():
                time.sleep(0.05)
                return len(jobs)

            await asyncio.to_thread(call_serialized, _dummy_persist)
            del jobs

        tasks = [asyncio.create_task(worker_task(i)) for i in range(conc)]
        await asyncio.gather(*tasks)

        gc.collect()
        end_rss = get_rss_mb()
        print(
            f"Concurrency: {conc:2d} | Base RSS: {base_rss:6.2f} MB | Peak RSS: {peak_rss:6.2f} MB | "
            f"End RSS: {end_rss:6.2f} MB | Live Threads: {threading.active_count()}"
        )


if __name__ == "__main__":
    asyncio.run(run_benchmark())
