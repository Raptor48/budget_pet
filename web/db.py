"""
Shared asyncpg connection pool singleton for V2 modules.

Usage:
    from web.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT ...")

JSONB/JSON handling
-------------------
asyncpg ships **without** a built-in codec for ``json``/``jsonb`` — by
default it returns/expects raw strings. Passing a Python ``dict`` to a
JSONB column without an explicit ``json.dumps()`` raises
``asyncpg.exceptions.DataError: ... (expected str, got dict)`` at INSERT
time. This is the official behaviour and the documented escape hatch is
to register codecs with ``conn.set_type_codec`` per connection
(`asyncpg usage docs
<https://magicstack.github.io/asyncpg/current/usage.html#example-automatic-json-conversion>`_).

We do that once per connection in :func:`_init_connection`, so every
caller can pass dicts/lists straight through without remembering to
serialise. The encoder is intentionally lenient: if the caller passed an
already-serialised string (the historical convention used in
``web/audit/repo.py``, ``web/notifications/queue.py``, etc.), it goes
through untouched — keeping the existing ``$N::jsonb`` cast call sites
working without churn. ``default=str`` lets the encoder swallow ``date``
/ ``datetime`` / ``Decimal`` values that occasionally sneak into
payloads (e.g. from OCR JSON or notification builders) instead of
raising ``TypeError`` at call time.
"""
import asyncio
import json
import logging
import os
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
_lock = asyncio.Lock()


def _jsonb_encode(value: Any) -> str:
    # Pre-serialised strings (legacy ``json.dumps(...)`` + ``$N::jsonb``
    # call sites) are already valid JSON — pass them through verbatim
    # rather than double-encoding into ``"\"...\""``.
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str, ensure_ascii=False)


def _jsonb_decode(value: str) -> Any:
    # asyncpg invokes the decoder with the raw JSON text; turn it into
    # a real Python object. Empty/None never reach here — asyncpg short-
    # circuits NULL columns to ``None`` before consulting the codec.
    return json.loads(value)


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Run once per pool connection. Registers the JSONB/JSON codec."""
    for type_name in ("json", "jsonb"):
        await conn.set_type_codec(
            type_name,
            encoder=_jsonb_encode,
            decoder=_jsonb_decode,
            schema="pg_catalog",
        )


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
            init=_init_connection,
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
