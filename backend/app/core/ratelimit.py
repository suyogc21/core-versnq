"""Fixed-window counters in Redis, shared by every API worker."""

import redis.asyncio as aioredis
from fastapi import HTTPException, status

from app.core.config import get_settings

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(get_settings().redis_url)
    return _client


def too_many() -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again later.")


async def hit(key: str, limit: int, window_seconds: int) -> bool:
    """Count one attempt; True while the window's count is within the limit."""
    r = get_redis()
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, window_seconds)
    return count <= limit


async def enforce(key: str, limit: int, window_seconds: int) -> None:
    if not await hit(key, limit, window_seconds):
        raise too_many()


async def count(key: str) -> int:
    value = await get_redis().get(key)
    return int(value or 0)


async def clear(key: str) -> None:
    await get_redis().delete(key)
