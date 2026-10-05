import asyncio
from arq.connections import create_pool
from app.workers.settings import redis_settings

async def check_redis_security():
    redis = await create_pool(redis_settings)
    
    # Check all ARQ keys
    keys = await redis.keys('arq:*')
    print(f"Total ARQ keys: {len(keys)}")
    
    # Check job data keys
    job_keys = [k for k in keys if b'arq:job:' in k]
    print(f"\nJob data keys: {len(job_keys)}")
    
    for key in job_keys[:3]:
        key_str = key.decode() if isinstance(key, bytes) else key
        job_data = await redis.get(key)
        if job_data:
            print(f"\nKey: {key_str}")
            print(f"  Data type: {type(job_data)}")
            if isinstance(job_data, bytes):
                job_data = job_data.decode('utf-8', errors='replace')
            print(f"  Data: {job_data[:200]}")
            
            # Check for sensitive data
            sensitive = ['jwt', 'token', 'password', 'secret', 'key', 'credential']
            job_lower = job_data.lower()
            for term in sensitive:
                if term in job_lower:
                    print(f"  WARNING: Found sensitive term '{term}'")
    
    # Check for any keys that might expose credentials
    all_keys = await redis.keys('*')
    print(f"\nAll Redis keys: {len(all_keys)}")
    for key in all_keys[:20]:
        print(f"  {key}")
    
    await redis.aclose()

asyncio.run(check_redis_security())
