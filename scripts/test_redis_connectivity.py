"""Phase 1C — Isolated redis.asyncio connectivity test.

Connects to the real Docker Redis, performs SET/GET, and cleans up.
Uses an isolated key namespace and does NOT interfere with existing data.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

from redis.asyncio import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
# Aiven Console URIs use valkey(s):// schemes; redis-py expects redis(s)://.
if REDIS_URL.startswith("valkeys://"):
    REDIS_URL = "rediss://" + REDIS_URL[len("valkeys://"):]
elif REDIS_URL.startswith("valkey://"):
    REDIS_URL = "redis://" + REDIS_URL[len("valkey://"):]
TEST_KEY_NAMESPACE = "careeros:infrastructure:test"


async def main() -> int:
    test_key = f"{TEST_KEY_NAMESPACE}:{uuid.uuid4().hex}"
    print(f"Connecting to Redis at {REDIS_URL} ...")

    redis = Redis.from_url(REDIS_URL)

    try:
        pong = await redis.ping()
        print(f"PING: {pong}")

        await redis.set(test_key, "hello-careeros")
        value = await redis.get(test_key)
        value_str = value.decode() if isinstance(value, bytes) else value
        print(f"SET/GET: key={test_key!r}  value={value_str!r}")

        if value_str != "hello-careeros":
            print("FAIL: SET/GET value mismatch")
            return 1

        await redis.delete(test_key)
        remaining = await redis.get(test_key)
        print(f"CLEANUP: key deleted, post-delete value={remaining!r}")

        print("redis.asyncio connectivity: PASS")
        return 0

    except Exception as exc:
        print(f"redis.asyncio connectivity: FAIL — {exc}")
        return 1

    finally:
        await redis.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
