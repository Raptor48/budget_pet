"""
Daily frontend warmup job — keeps the Next.js container off cold-start.

The FastAPI process is kept warm by the per-minute notification
dispatcher, but Next.js has no internal heartbeat. When the user goes
hours without opening the web UI the first pageload pays a ~30s
cold-start. A single GET per day to ``PUBLIC_FRONTEND_URL`` is enough to
keep the container, the Railway edge, and the TLS session warm.

Three things must hold:
  1. With the env var set we issue exactly one GET to the configured URL.
  2. With the env var unset (or empty) the job is a complete no-op — no
     network call, no exception.
  3. Network failures are swallowed at INFO level — a missed warmup is
     harmless and must never fail the scheduler tick.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_warmup_hits_frontend_url_when_env_var_set(monkeypatch):
    """Env var present ⇒ one GET to ``<base>/``."""
    from web.notifications import dispatcher

    monkeypatch.setenv("PUBLIC_FRONTEND_URL", "https://app.example.com")

    captured: dict = {}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url):
            captured["url"] = url
            resp = MagicMock()
            resp.status_code = 200
            return resp

    fake_httpx = MagicMock()
    fake_httpx.AsyncClient = _FakeClient
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        await dispatcher._daily_warmup_frontend()

    assert captured["url"] == "https://app.example.com/"
    # Sanity-check the timeout was passed (cold-start can take a while —
    # 15s is a safe ceiling for a hobby-tier free-tier wake).
    assert captured["client_kwargs"].get("timeout") == 15.0


@pytest.mark.asyncio
async def test_warmup_noop_when_env_var_unset(monkeypatch):
    """No env var ⇒ never imports httpx, never raises. Local dev path."""
    from web.notifications import dispatcher

    monkeypatch.delenv("PUBLIC_FRONTEND_URL", raising=False)

    # If the implementation accidentally tried to make a request, replacing
    # httpx with a stub that raises gives us a loud regression signal.
    fake_httpx = MagicMock()
    fake_httpx.AsyncClient.side_effect = AssertionError(
        "warmup must not call httpx when PUBLIC_FRONTEND_URL is unset"
    )
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        await dispatcher._daily_warmup_frontend()  # must not raise


@pytest.mark.asyncio
async def test_warmup_swallows_network_errors(monkeypatch):
    """A failed ping is harmless — the next user pageload pays the cost
    once and the job tick must not propagate the error."""
    from web.notifications import dispatcher

    monkeypatch.setenv("PUBLIC_FRONTEND_URL", "https://app.example.com")

    class _BoomClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url):
            raise ConnectionError("simulated edge timeout")

    fake_httpx = MagicMock()
    fake_httpx.AsyncClient = _BoomClient
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        # Must NOT raise — the scheduler would otherwise mark the job
        # broken.
        await dispatcher._daily_warmup_frontend()


@pytest.mark.asyncio
async def test_warmup_uses_first_csv_entry(monkeypatch):
    """``PUBLIC_FRONTEND_URL`` may legitimately be a CSV (CORS reuse).
    Match the handler convention: first entry wins."""
    from web.notifications import dispatcher

    monkeypatch.setenv(
        "PUBLIC_FRONTEND_URL",
        "https://app.example.com,https://staging.example.com",
    )

    captured: dict = {}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url):
            captured["url"] = url
            resp = MagicMock()
            resp.status_code = 200
            return resp

    fake_httpx = MagicMock()
    fake_httpx.AsyncClient = _FakeClient
    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        await dispatcher._daily_warmup_frontend()

    assert captured["url"] == "https://app.example.com/"
