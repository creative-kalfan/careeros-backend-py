import time
import logging
from app.workers.settings import get_redis_pool

logger = logging.getLogger(__name__)

LUA_TOKEN_BUCKET = """
local tokens_key = KEYS[1]
local timestamp_key = KEYS[2]
local capacity = tonumber(ARGV[1])
local fill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local last_tokens = tonumber(redis.call("get", tokens_key))
if last_tokens == nil then
    last_tokens = capacity
end

local last_refreshed = tonumber(redis.call("get", timestamp_key))
if last_refreshed == nil then
    last_refreshed = now
end

local delta = math.max(0, now - last_refreshed)
local filled_tokens = math.min(capacity, last_tokens + (delta * fill_rate))
local allowed = filled_tokens >= 1

if allowed then
    filled_tokens = filled_tokens - 1
    redis.call("setex", tokens_key, 86400, filled_tokens)
    redis.call("setex", timestamp_key, 86400, now)
    return 1
end
return 0
"""

async def check_rate_limit(platform: str, capacity: int, window_seconds: int) -> bool:
    """Check if the given platform has tokens available. Uses a Token Bucket algorithm."""
    try:
        redis = await get_redis_pool()
        now = time.time()
        fill_rate = capacity / float(window_seconds) if window_seconds > 0 else 0
        
        tokens_key = f"rate_limit:tokens:{platform}"
        timestamp_key = f"rate_limit:ts:{platform}"
        
        # ARQ's arq.connections.Redis is a wrapper over redis.asyncio.Redis
        # We can evaluate the lua script
        allowed = await redis.eval(
            LUA_TOKEN_BUCKET,
            2,
            tokens_key, timestamp_key,
            capacity, fill_rate, now
        )
        return bool(allowed)
    except Exception as e:
        logger.warning(f"Rate limiter failed for {platform}, failing open: {e}")
        return True
