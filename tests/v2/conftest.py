"""
V2 test fixtures and configuration.
"""
import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def make_mock_pool(conn: AsyncMock):
    """
    Create a correctly-configured mock asyncpg Pool.

    asyncpg usage pattern:
        async with pool.acquire() as conn: ...

    pool.acquire() must be a regular function that returns an async context manager.
    """
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def make_record(**kwargs) -> Dict[str, Any]:
    """Create a mock asyncpg Record-like dict."""
    return dict(**kwargs)
