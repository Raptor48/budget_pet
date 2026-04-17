"""
Shared asyncpg connection pool singleton for V2 modules.

Usage:
    from web.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT ...")
"""
import asyncio
import logging
import os
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    """Return the shared asyncpg pool, creating it on first call."""
    global _pool
    if _pool is not None:
        return _pool
    async with _lock:
        if _pool is not None:
            return _pool
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL environment variable is not set")
        logger.info("Creating asyncpg connection pool...")
        _pool = await asyncpg.create_pool(
            dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
            server_settings={"application_name": "budget_pet_v2"},
        )
        logger.info("asyncpg pool created successfully.")
    return _pool


async def close_pool() -> None:
    """Gracefully close the connection pool on shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("asyncpg pool closed.")
