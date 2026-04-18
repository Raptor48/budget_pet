"""Tests for the webhooks_enabled toggle end-to-end behaviour.

Focus: *behaviour the user cares about* — the toggle actually stops Plaid from
billing us and we never ship a half-disabled state.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# /api/plaid/webhook short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_endpoint_short_circuits_when_toggle_off(monkeypatch):
    """Incoming webhooks must be a no-op when the in-app toggle is off.

    Stale registrations or delayed Plaid propagation can still cause pushes to
    arrive after we've flipped the toggle — this guard ensures we don't kick
    off a debounced sync (which would cost money).
    """
    from web.plaid import routes as plaid_routes

    async def fake_flag():
        return False

    schedule_mock = MagicMock()

    # Any access to request body / verify should never happen when disabled.
    class FakeRequest:
        async def body(self):  # pragma: no cover — must not be awaited
            raise AssertionError("body() should not be read when webhooks disabled")

        headers: dict[str, str] = {}

    with patch.object(plaid_routes, "_webhooks_enabled", fake_flag), \
         patch("web.plaid.scheduler.schedule_debounced_sync_item", schedule_mock):
        result = await plaid_routes.plaid_webhook(FakeRequest())  # type: ignore[arg-type]

    assert result == {"status": "disabled"}
    schedule_mock.assert_not_called()


# ---------------------------------------------------------------------------
# /api/plaid/link-token passes webhook override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_token_omits_webhook_when_flag_is_off():
    """New Link tokens created while the toggle is off must not carry a
    webhook URL — otherwise fresh bank connections would re-opt us back in."""
    from web.plaid import routes as plaid_routes

    captured: dict = {}

    def fake_create_link_token(**kwargs):
        captured.update(kwargs)
        return {"link_token": "lt-1", "expiration": "2099-01-01"}

    class FakeRequest:
        class state:
            user = {"id": 1, "username": "owner"}
        headers: dict[str, str] = {}

    async def flag_off():
        return False

    from web.plaid.models import LinkTokenBody

    with patch.object(plaid_routes, "create_link_token", fake_create_link_token), \
         patch.object(plaid_routes, "_webhooks_enabled", flag_off):
        await plaid_routes.get_link_token(FakeRequest(), LinkTokenBody())  # type: ignore[arg-type]

    # Explicit empty-string override signals "create without webhook" to the client.
    assert captured.get("webhook_url_override") == ""


@pytest.mark.asyncio
async def test_link_token_uses_env_webhook_when_flag_is_on():
    from web.plaid import routes as plaid_routes
    from web.plaid.models import LinkTokenBody

    captured: dict = {}

    def fake_create_link_token(**kwargs):
        captured.update(kwargs)
        return {"link_token": "lt-2", "expiration": "2099-01-01"}

    class FakeRequest:
        class state:
            user = {"id": 1, "username": "owner"}
        headers: dict[str, str] = {}

    async def flag_on():
        return True

    with patch.object(plaid_routes, "create_link_token", fake_create_link_token), \
         patch.object(plaid_routes, "_webhooks_enabled", flag_on):
        await plaid_routes.get_link_token(FakeRequest(), LinkTokenBody())  # type: ignore[arg-type]

    # `None` means "fall back to env var" which preserves prior behaviour.
    assert captured.get("webhook_url_override") is None


# ---------------------------------------------------------------------------
# reconcile_item_webhooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_clears_webhook_on_every_item_when_disabling(monkeypatch):
    from web.plaid import webhook_config

    plaid_repo = AsyncMock()
    plaid_repo.get_items = AsyncMock(
        return_value=[
            {"item_id": "a", "access_token": "tok-a"},
            {"item_id": "b", "access_token": "tok-b"},
            {"item_id": "c", "access_token": None},  # skipped
        ]
    )

    calls: list[tuple[str, str]] = []

    def fake_update(access_token: str, webhook: str) -> bool:
        calls.append((access_token, webhook))
        return True

    monkeypatch.setenv("PLAID_WEBHOOK_URL", "https://example.com/hook")

    with patch.object(webhook_config, "get_plaid_repo", return_value=plaid_repo), \
         patch.object(webhook_config, "update_item_webhook", fake_update):
        summary = await webhook_config.reconcile_item_webhooks(False)

    assert calls == [("tok-a", ""), ("tok-b", "")]
    assert summary["updated"] == 2
    assert summary["failed"] == 0
    assert summary["total"] == 2


@pytest.mark.asyncio
async def test_reconcile_counts_failures(monkeypatch):
    from web.plaid import webhook_config

    plaid_repo = AsyncMock()
    plaid_repo.get_items = AsyncMock(
        return_value=[
            {"item_id": "a", "access_token": "tok-a"},
            {"item_id": "b", "access_token": "tok-b"},
        ]
    )

    def fake_update(access_token: str, webhook: str) -> bool:
        return access_token != "tok-b"  # second one fails

    monkeypatch.setenv("PLAID_WEBHOOK_URL", "https://example.com/hook")

    with patch.object(webhook_config, "get_plaid_repo", return_value=plaid_repo), \
         patch.object(webhook_config, "update_item_webhook", fake_update):
        summary = await webhook_config.reconcile_item_webhooks(True)

    assert summary["updated"] == 1
    assert summary["failed"] == 1
    assert summary["total"] == 2
    assert any("item b" in err for err in summary["errors"])
