"""Probe Upstash Redis (production) for crawl status + ARQ queue state."""
import asyncio
import json

UPSTASH = "rediss://default:gQAAAAAAAkhLAAIgcDEyY2UwNTczNDk4YTg0YzhmOGRmNWUzMWZiN2ZkNDMyNA@sincere-hagfish-149579.upstash.io:6379"


async def main():
    from arq.connections import RedisSettings, create_pool

    rs = RedisSettings.from_dsn(UPSTASH)
    pool = await create_pool(rs)
    try:
        pong = await pool.ping()
        print("Upstash ping:", pong)
        q = await pool.zcard("arq:queue")
        s = await pool.zcard("arq:queue:started")
        print("arq queue depth:", q, "started:", s)

        keys = []
        async for k in pool.scan_iter(match="crawl_status:*", count=100):
            kk = k.decode() if isinstance(k, bytes) else k
            keys.append(kk)
        print("crawl_status keys:", len(keys))
        for k in sorted(keys):
            raw = await pool.get(k)
            if not raw:
                continue
            d = json.loads(raw)
            print(
                f"  {k}: status={d.get('status')} completed={d.get('completed_at')} "
                f"inserted={d.get('inserted')} discovered={d.get('discovered')} "
                f"error={str(d.get('error', ''))[:100]}"
            )

        arq_keys = []
        async for k in pool.scan_iter(match="arq:*", count=300):
            kk = k.decode() if isinstance(k, bytes) else k
            arq_keys.append(kk)
        print("arq keys count:", len(arq_keys))
        for k in sorted(arq_keys)[:50]:
            print(" ", k)

        lock_keys = []
        async for k in pool.scan_iter(match="crawl_lock:*", count=100):
            kk = k.decode() if isinstance(k, bytes) else k
            lock_keys.append(kk)
        print("crawl_lock keys:", lock_keys)

        # health key (ARQ worker health check)
        for hk in ("arq:health", "arq:worker_health", "health"):
            v = await pool.get(hk)
            if v:
                print(f"health {hk}: {v}")
    finally:
        await pool.aclose()


if __name__ == "__main__":
    asyncio.run(main())
