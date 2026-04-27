"""
V2 test fixtures and configuration.
"""
# Compatibility shim — local FastAPI/Starlette pairs that ship a newer
# Starlette (≥ 0.41) drop ``on_startup``/``on_shutdown`` kwargs from the
# base ``Router.__init__``, but FastAPI 0.116 still forwards them. The
# resulting ``TypeError: ... unexpected keyword argument 'on_startup'``
# fires at module-import time inside every ``APIRouter(prefix=…)`` call
# across the codebase, blocking pytest collection before any test even
# runs. Strip the kwargs so router construction is harmless. Production
# pins the matching versions and never sees this; the patch is invisible
# at runtime there.
import starlette.routing as _starlette_routing

_orig_router_init = _starlette_routing.Router.__init__


def _compat_router_init(self, *args, **kwargs):
    # FastAPI's ``include_router`` later reads ``router.on_startup`` /
    # ``on_shutdown`` directly (see fastapi/routing.py: for handler in
    # router.on_startup). Preserve them as empty lists on the instance
    # so that path doesn't ``AttributeError`` after we strip the kwarg.
    on_startup = kwargs.pop("on_startup", None) or []
    on_shutdown = kwargs.pop("on_shutdown", None) or []
    _orig_router_init(self, *args, **kwargs)
    self.on_startup = on_startup
    self.on_shutdown = on_shutdown


def _compat_add_event_handler(self, event_type, func):
    # Deprecated path used by ``@app.on_event('startup')``. Newer
    # Starlette dropped it; FastAPI still calls it. No-op is fine for
    # tests since the suite runs handlers explicitly via fixtures.
    if event_type == "startup":
        self.on_startup.append(func)
    else:
        self.on_shutdown.append(func)


_starlette_routing.Router.add_event_handler = _compat_add_event_handler


_starlette_routing.Router.__init__ = _compat_router_init

import asyncio  # noqa: E402
from typing import Any, Dict  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402


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
