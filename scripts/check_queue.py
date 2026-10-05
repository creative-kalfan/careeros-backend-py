import asyncio
from arq.connections import create_pool
from app.workers.settings import redis_settings

async def check_queue():
    redis = await create_pool(redis_settings)
    
    # Check for ARQ keys
    keys = await redis.keys('arq:*')
    print(f"ARQ keys: {len(keys)}")
    for key in keys[:10]:
        print(f"  {key}")
    
    # Check queue length
    queue_key = 'arq:queue'
    queue_length = await redis.llen(queue_key)
    print(f"\nQueue length: {queue_length}")
    
    # Check for the specific job
    job_id = 'd003978a6e3f43d0b6f6a507e561c68c'
    job_keys = await redis.keys(f'*{job_id}*')
    print(f"\nKeys containing job ID: {len(job_keys)}")
    for key in job_keys:
        print(f"  {key}")
    
    await redis.aclose()

asyncio.run(check_queue())
