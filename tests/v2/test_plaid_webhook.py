"""Plaid webhook route — idempotency, flag updates, and JWT verification (unit tests)."""
import hashlib
import json
import os
import time
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# Unit tests for verify_plaid_webhook — body hash and iat validation
# ---------------------------------------------------------------------------

def _make_request(token: str | None = None) -> MagicMock:
    req = MagicMock()
    req.headers = {}
    if token:
        req.headers["Plaid-Verification"] = token
    return req


def test_verify_skip_env(monkeypatch):
    """PLAID_SKIP_WEBHOOK_VERIFY=true always returns True."""
    monkeypatch.setenv("PLAID_SKIP_WEBHOOK_VERIFY", "true")
    from web.plaid.webhook_verify import verify_plaid_webhook
    assert verify_plaid_webhook(_make_request("ignored"), b"body") is True


def test_verify_no_token_sandbox(monkeypatch):
    """Missing JWT header is OK in sandbox (Plaid test webhooks may omit it)."""
    monkeypatch.setenv("PLAID_SKIP_WEBHOOK_VERIFY", "")
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    from web.plaid.webhook_verify import verify_plaid_webhook
    assert verify_plaid_webhook(_make_request(None), b"body") is True


def test_verify_no_token_production(monkeypatch):
    """Missing JWT header must be rejected in production."""
    monkeypatch.setenv("PLAID_SKIP_WEBHOOK_VERIFY", "")
    monkeypatch.setenv("PLAID_ENV", "production")
    from web.plaid.webhook_verify import verify_plaid_webhook
    assert verify_plaid_webhook(_make_request(None), b"body") is False


def test_verify_body_hash_mismatch(monkeypatch):
    """Correct JWT signature but wrong body hash → rejected."""
    monkeypatch.setenv("PLAID_SKIP_WEBHOOK_VERIFY", "")
    monkeypatch.setenv("PLAID_ENV", "production")

    body = b'{"test": 1}'
    correct_hash = hashlib.sha256(body).hexdigest()
    wrong_hash = "0" * 64

    jwt_payload = {"iat": int(time.time()), "request_body_sha256": wrong_hash}

    with patch("web.plaid.webhook_verify.PyJWKClient") as mock_jwks_cls:
        mock_jwks = MagicMock()
        mock_jwks_cls.return_value = mock_jwks
        mock_signing_key = MagicMock()
        mock_jwks.get_signing_key_from_jwt.return_value = mock_signing_key

        with patch("web.plaid.webhook_verify.jwt") as mock_jwt:
            mock_jwt.decode.return_value = jwt_payload
            from web.plaid.webhook_verify import verify_plaid_webhook
            result = verify_plaid_webhook(_make_request("fake.jwt.token"), body)

    assert result is False


def test_verify_iat_too_old(monkeypatch):
    """JWT with iat > 5 minutes ago → rejected (replay attack)."""
    monkeypatch.setenv("PLAID_SKIP_WEBHOOK_VERIFY", "")
    monkeypatch.setenv("PLAID_ENV", "production")

    body = b'{"test": 1}'
    stale_iat = int(time.time()) - 400  # 6+ minutes ago
    jwt_payload = {
        "iat": stale_iat,
        "request_body_sha256": hashlib.sha256(body).hexdigest(),
    }

    with patch("web.plaid.webhook_verify.PyJWKClient") as mock_jwks_cls:
        mock_jwks = MagicMock()
        mock_jwks_cls.return_value = mock_jwks
        mock_jwks.get_signing_key_from_jwt.return_value = MagicMock()

        with patch("web.plaid.webhook_verify.jwt") as mock_jwt:
            mock_jwt.decode.return_value = jwt_payload
            from web.plaid.webhook_verify import verify_plaid_webhook
            result = verify_plaid_webhook(_make_request("fake.jwt.token"), body)

    assert result is False


def test_verify_valid(monkeypatch):
    """Valid JWT signature + fresh iat + correct body hash → accepted."""
    monkeypatch.setenv("PLAID_SKIP_WEBHOOK_VERIFY", "")
    monkeypatch.setenv("PLAID_ENV", "production")

    body = b'{"test": 1}'
    jwt_payload = {
        "iat": int(time.time()),
        "request_body_sha256": hashlib.sha256(body).hexdigest(),
    }

    with patch("web.plaid.webhook_verify.PyJWKClient") as mock_jwks_cls:
        mock_jwks = MagicMock()
        mock_jwks_cls.return_value = mock_jwks
        mock_jwks.get_signing_key_from_jwt.return_value = MagicMock()

        with patch("web.plaid.webhook_verify.jwt") as mock_jwt:
            mock_jwt.decode.return_value = jwt_payload
            from web.plaid.webhook_verify import verify_plaid_webhook
            result = verify_plaid_webhook(_make_request("fake.jwt.token"), body)

    assert result is True


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
