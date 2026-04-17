"""
Transactions days_requested wiring for Plaid Link token creation.

Validates the get_plaid_transactions_days_requested() helper and ensures both
link-modes (new connect and update-mode with access_token) pass the value via
LinkTokenTransactions.days_requested to Plaid.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from plaid.model.link_token_create_request import LinkTokenCreateRequest

from web.plaid.constants import (
    DEFAULT_PLAID_TRANSACTIONS_DAYS_REQUESTED,
    MAX_PLAID_TRANSACTIONS_DAYS_REQUESTED,
    MIN_PLAID_TRANSACTIONS_DAYS_REQUESTED,
    get_plaid_transactions_days_requested,
)


def test_default_is_730():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PLAID_TRANSACTIONS_DAYS_REQUESTED", None)
        assert get_plaid_transactions_days_requested() == DEFAULT_PLAID_TRANSACTIONS_DAYS_REQUESTED
        assert DEFAULT_PLAID_TRANSACTIONS_DAYS_REQUESTED == 730


def test_env_override_respected():
    with patch.dict(os.environ, {"PLAID_TRANSACTIONS_DAYS_REQUESTED": "90"}):
        assert get_plaid_transactions_days_requested() == 90


def test_invalid_env_falls_back_to_default():
    with patch.dict(os.environ, {"PLAID_TRANSACTIONS_DAYS_REQUESTED": "banana"}):
        assert get_plaid_transactions_days_requested() == DEFAULT_PLAID_TRANSACTIONS_DAYS_REQUESTED


def test_clamping_to_plaid_limits():
    with patch.dict(os.environ, {"PLAID_TRANSACTIONS_DAYS_REQUESTED": "0"}):
        assert get_plaid_transactions_days_requested() == MIN_PLAID_TRANSACTIONS_DAYS_REQUESTED
    with patch.dict(os.environ, {"PLAID_TRANSACTIONS_DAYS_REQUESTED": "9999"}):
        assert get_plaid_transactions_days_requested() == MAX_PLAID_TRANSACTIONS_DAYS_REQUESTED


def _capture_link_token_request(access_token: str | None = None) -> LinkTokenCreateRequest:
    """Invoke create_link_token with Plaid API mocked and return the captured request."""
    captured = {}

    def fake_create(request: LinkTokenCreateRequest):
        captured["request"] = request
        response = MagicMock()
        response.to_dict.return_value = {
            "link_token": "link-sandbox-123",
            "expiration": "2099-01-01T00:00:00Z",
        }
        return response

    api = MagicMock()
    api.link_token_create = MagicMock(side_effect=fake_create)

    # Stable env for the test: known days value, no webhook, no redirect.
    env_overrides = {"PLAID_TRANSACTIONS_DAYS_REQUESTED": "730"}
    env_clears = [
        "PLAID_OPTIONAL_PRODUCTS",
        "PLAID_WEBHOOK_URL",
        "PLAID_REDIRECT_URI",
        "PLAID_ENABLE_INVESTMENTS",
    ]
    with patch.dict(os.environ, env_overrides):
        for k in env_clears:
            os.environ.pop(k, None)
        with patch("web.plaid.client.get_plaid_client", return_value=api):
            from web.plaid.client import create_link_token

            create_link_token(user_id="user-42", access_token=access_token)

    return captured["request"]


def test_create_link_token_new_connection_sends_days_requested():
    """New Link flow must include transactions.days_requested=730."""
    request = _capture_link_token_request(access_token=None)
    txn_opts = getattr(request, "transactions", None)
    assert txn_opts is not None, "LinkTokenCreateRequest must carry a transactions block"
    assert getattr(txn_opts, "days_requested", None) == 730
    # Sanity: new connection has products, not access_token.
    assert not hasattr(request, "access_token") or getattr(request, "access_token", None) in (None, "")


def test_create_link_token_update_mode_sends_days_requested():
    """Update-mode (access_token) must also pass transactions.days_requested so Plaid extends history."""
    request = _capture_link_token_request(access_token="access-sandbox-existing")
    txn_opts = getattr(request, "transactions", None)
    assert txn_opts is not None, "update-mode LinkTokenCreateRequest must carry a transactions block"
    assert getattr(txn_opts, "days_requested", None) == 730
    assert getattr(request, "access_token", None) == "access-sandbox-existing"
