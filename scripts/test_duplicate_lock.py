import asyncio
from arq.connections import create_pool
from app.workers.settings import redis_settings
from app.workers.enqueue import enqueue_crawl_company

async def test_duplicate_lock():
    # First, clear any existing locks
    redis = await create_pool(redis_settings)
    keys = await redis.keys('crawl_lock:*')
    for key in keys:
        await redis.delete(key)
        print(f"Cleared existing lock: {key}")
    await redis.aclose()
    
    print("\n=== Testing Duplicate Lock ===")
    
    # Enqueue two crawls for the same company simultaneously
    job_id_1 = await enqueue_crawl_company("greenhouse", "stripe")
    job_id_2 = await enqueue_crawl_company("greenhouse", "stripe")
    
    print(f"First enqueue: {job_id_1}")
    print(f"Second enqueue: {job_id_2}")
    
    # Check the lock in Redis
    redis = await create_pool(redis_settings)
    lock_key = "crawl_lock:greenhouse:stripe"
    lock_exists = await redis.exists(lock_key)
    ttl = await redis.ttl(lock_key)
    
    print(f"\nLock key: {lock_key}")
    print(f"Lock exists: {lock_exists}")
    print(f"Lock TTL: {ttl} seconds")
    
    # Verify expected behavior
    assert job_id_1 is not None, "First crawl should be enqueued"
    assert job_id_2 is None, "Second crawl should be skipped (lock exists)"
    assert lock_exists == 1, "Lock should exist in Redis"
    assert ttl > 0 and ttl <= 300, f"Lock TTL should be <= 300s, got {ttl}"
    
    print("\n✓ PASS: Duplicate lock works correctly")
    
    # Clean up: delete the lock
    await redis.delete(lock_key)
    print(f"Cleaned up lock: {lock_key}")
    await redis.aclose()

asyncio.run(test_duplicate_lock())
