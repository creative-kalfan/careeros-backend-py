import asyncio
from arq.connections import create_pool
from app.workers.settings import redis_settings

async def get_job_result():
    redis = await create_pool(redis_settings)
    
    job_ids = [
        '65643898d01a42909748098f4c214309',  # First crawl
        '9c0f8d974581473da8c801dedd799b3e',  # Second crawl
    ]
    
    for job_id in job_ids:
        try:
            result = await redis._get_job_result(job_id)
            if result and hasattr(result, 'result'):
                print(f"\nJob {job_id}:")
                print(f"  Result: {result.result}")
            else:
                print(f"\nJob {job_id}: No result found")
        except Exception as e:
            print(f"\nJob {job_id}: Error - {e}")
    
    await redis.aclose()

asyncio.run(get_job_result())
