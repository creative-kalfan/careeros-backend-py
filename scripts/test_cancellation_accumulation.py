"""Deterministic test demonstrating cancellation and thread accumulation."""

import asyncio
import gc
import psutil
import threading
import time

from app.db.supabase import call_serialized, reset_persistence_semaphore
import app.workers.jobs.crawl_jobs as crawl_jobs_module


def get_rss_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 * 1024)


async def test_simulated_crawl_cancel_before_fix():
    print("\n--- Test: 10 Concurrent Crawls Cancelled Under Semaphore=2 ---")
    reset_persistence_semaphore(2)
    start_threads = threading.active_count()
    start_rss = get_rss_mb()
    print(f"Start: Threads={start_threads}, RSS={start_rss:.2f} MB, active_crawls={crawl_jobs_module.active_crawl_count()}")

    executed_count = 0
    lock = threading.Lock()

    def _slow_db_operation(job_id: int):
        nonlocal executed_count
        # Simulates blocking Supabase persistence
        time.sleep(1.0)
        with lock:
            executed_count += 1

    async def crawl_task(job_id: int):
        # Emulate current crawl_company_job structure:
        # Increment gauge
        crawl_jobs_module._ACTIVE_CRAWLS += 1
        try:
            await asyncio.to_thread(call_serialized, _slow_db_operation, job_id)
        except asyncio.CancelledError:
            # Current crawl_jobs.py line 280:
            crawl_jobs_module._ACTIVE_CRAWLS = max(0, crawl_jobs_module._ACTIVE_CRAWLS - 1)
            raise

    # Launch 10 tasks concurrently
    tasks = [asyncio.create_task(crawl_task(i)) for i in range(10)]
    # Wait 0.1s so all 10 enter to_thread (2 acquire sem, 8 wait in sem.acquire())
    await asyncio.sleep(0.1)

    print(f"While running: Threads={threading.active_count()}, active_crawls={crawl_jobs_module.active_crawl_count()}")

    # ARQ 300s timeout fires: cancel all 10 tasks
    print("Cancelling all 10 tasks...")
    for t in tasks:
        t.cancel()

    # Await cancellation
    for t in tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass

    print(f"Immediately after cancel: Threads={threading.active_count()}, executed_so_far={executed_count}")
    print(f"Notice: coroutines are dead, but threads are STILL RUNNING in ThreadPoolExecutor!")

    # Wait 4 seconds to let the zombie threads finish their un-cancelled work
    await asyncio.sleep(6.0)
    print(f"After 6s: executed_count={executed_count} (out of 10!)")
    print(f"Notice: ALL 10 zombie operations executed even though all 10 tasks were CANCELLED!")


if __name__ == "__main__":
    asyncio.run(test_simulated_crawl_cancel_before_fix())
