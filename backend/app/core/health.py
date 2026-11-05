import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal

CHECK_TIMEOUT_SECONDS = 2

router = APIRouter()


async def _db_check() -> None:
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))


def get_db_check() -> Callable[[], Awaitable[None]]:
    return _db_check


def get_redis_url() -> str:
    return get_settings().redis_url


async def _redis_check(url: str) -> None:
    client = aioredis.from_url(url, socket_connect_timeout=CHECK_TIMEOUT_SECONDS)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _status(check: Awaitable[None]) -> str:
    try:
        await asyncio.wait_for(check, CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        return "down"


@router.get("/health")
async def health(
    db_check: Annotated[Callable[[], Awaitable[None]], Depends(get_db_check)],
    redis_url: Annotated[str, Depends(get_redis_url)],
) -> JSONResponse:
    db, redis = await asyncio.gather(_status(db_check()), _status(_redis_check(redis_url)))
    ok = db == "ok" and redis == "ok"
    body = {"status": "ok" if ok else "degraded", "db": db, "redis": redis}
    return JSONResponse(body, status_code=200 if ok else 503)
