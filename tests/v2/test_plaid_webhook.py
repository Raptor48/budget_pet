"""Plaid webhook route — idempotency and flag updates (JWT skipped in tests)."""
import json
import os

import pytest
from httpx import ASGITransport, AsyncClient

from web.main import app


@pytest.fixture(autouse=True)
def _webhook_skip_verify(monkeypatch):
    monkeypatch.setenv("PLAID_SKIP_WEBHOOK_VERIFY", "true")


@pytest.mark.asyncio
async def test_webhook_item_login_required(monkeypatch):
    from web.plaid import repo as plaid_repo_mod

    called = {}

    async def fake_set(self, item_id, value=True):
        called["item"] = item_id
        called["val"] = value

    async def fake_try_insert(self, wid):
        return True

    monkeypatch.setattr(plaid_repo_mod.PlaidRepository, "set_item_login_required", fake_set)
    monkeypatch.setattr(plaid_repo_mod.PlaidRepository, "try_insert_webhook_event", fake_try_insert)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = {
            "webhook_type": "ITEM",
            "webhook_code": "ITEM_LOGIN_REQUIRED",
            "item_id": "itm_test",
            "webhook_id": "wh_1",
        }
        r = await client.post("/api/plaid/webhook", content=json.dumps(body), headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert called.get("item") == "itm_test"


@pytest.mark.asyncio
async def test_webhook_duplicate_ignored(monkeypatch):
    from web.plaid import repo as plaid_repo_mod

    async def fake_try_insert(self, wid):
        return False

    monkeypatch.setattr(plaid_repo_mod.PlaidRepository, "try_insert_webhook_event", fake_try_insert)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = {"webhook_type": "ITEM", "webhook_code": "ITEM_LOGIN_REQUIRED", "item_id": "x", "webhook_id": "wh_dup"}
        r = await client.post("/api/plaid/webhook", content=json.dumps(body), headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert r.json().get("status") == "duplicate"
