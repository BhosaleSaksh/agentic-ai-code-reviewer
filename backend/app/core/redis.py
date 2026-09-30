"""Asynchronous Redis client and connection utility.

Provides async Redis client instances and connectivity healthchecks
driven by app.core.config.
"""

import asyncio
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from arq.connections import ArqRedis

from app.core.config import get_settings


def get_redis_client() -> aioredis.Redis:
    """Return an asynchronous Redis client instance."""
    settings = get_settings()
    return aioredis.from_url(
        settings.effective_redis_url,
        encoding="utf-8",
        decode_responses=True,
    )


async def _close_redis_client(client: aioredis.Redis) -> None:
    """Close redis client using aclose if available or fallback to close."""
    aclose_func = getattr(client, "aclose", None)
    if callable(aclose_func):
        await aclose_func()
    else:
        await client.close()


async def get_redis_session() -> AsyncGenerator[aioredis.Redis, None]:
    """Yield an async Redis client and close connection cleanly upon exit."""
    client = get_redis_client()
    try:
        yield client
    finally:
        await _close_redis_client(client)


async def check_redis_connection() -> bool:
    """Verify Redis connectivity with an async PING command."""
    client = get_redis_client()
    try:
        response = await client.ping()
        return response is True
    finally:
        await _close_redis_client(client)


_arq_redis_pool: ArqRedis | None = None
_arq_pool_loop: asyncio.AbstractEventLoop | None = None


async def get_arq_redis_pool() -> ArqRedis:
    """Return shared ArqRedis connection pool for job enqueueing."""
    global _arq_redis_pool, _arq_pool_loop
    current_loop = asyncio.get_running_loop()
    if _arq_redis_pool is not None and _arq_pool_loop != current_loop:
        _arq_redis_pool = None
        _arq_pool_loop = None

    if _arq_redis_pool is None:
        from arq.connections import create_pool

        settings = get_settings()
        _arq_redis_pool = await create_pool(settings.arq_redis_settings)
        _arq_pool_loop = current_loop
    return _arq_redis_pool


async def close_arq_redis_pool() -> None:
    """Close shared ArqRedis connection pool cleanly."""
    global _arq_redis_pool, _arq_pool_loop
    if _arq_redis_pool is not None:
        try:
            aclose_fn = getattr(_arq_redis_pool, "aclose", None)
            if callable(aclose_fn):
                await aclose_fn()
            else:
                await _arq_redis_pool.close()
        except Exception:
            pass
        _arq_redis_pool = None
        _arq_pool_loop = None
