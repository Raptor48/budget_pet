"""Plaid PFC version helper and client request wiring."""
import os
from unittest.mock import MagicMock, patch

import pytest

from datetime import datetime, timedelta, timezone

from web.plaid.constants import (
    DEFAULT_PLAID_PFC_CATEGORY_VERSION,
    MAX_PLAID_TRANSACTIONS_DAYS_REQUESTED,
    get_balance_min_last_updated_datetime,
    get_plaid_pfc_category_version,
)


def test_get_balance_min_last_updated_datetime_uses_max_history_window():
    dt = get_balance_min_last_updated_datetime()
    assert dt.tzinfo is not None
    age = datetime.now(timezone.utc) - dt
    assert timedelta(days=MAX_PLAID_TRANSACTIONS_DAYS_REQUESTED - 1) < age
    assert age < timedelta(days=MAX_PLAID_TRANSACTIONS_DAYS_REQUESTED + 1)


def test_get_plaid_pfc_category_version_env():
    with patch.dict(os.environ, {"PLAID_PERSONAL_FINANCE_CATEGORY_VERSION": "bogus"}):
        assert get_plaid_pfc_category_version() == DEFAULT_PLAID_PFC_CATEGORY_VERSION
    with patch.dict(os.environ, {"PLAID_PERSONAL_FINANCE_CATEGORY_VERSION": "v1"}):
        assert get_plaid_pfc_category_version() == "v1"
    with patch.dict(os.environ, {"PLAID_PERSONAL_FINANCE_CATEGORY_VERSION": "V2"}):
        assert get_plaid_pfc_category_version() == "v2"


@pytest.mark.asyncio
async def test_transactions_sync_request_includes_pfc_version():
    """transactions_sync receives options.personal_finance_category_version."""
    from plaid.model.transactions_sync_request import TransactionsSyncRequest

    captured = {}

    def fake_sync(request: TransactionsSyncRequest):
        captured["options"] = request.options
        return {
            "added": [],
            "modified": [],
            "removed": [],
            "has_more": False,
            "next_cursor": "c1",
        }

    with patch.dict(os.environ, {"PLAID_PERSONAL_FINANCE_CATEGORY_VERSION": "v2"}):
        with patch("web.plaid.client.get_plaid_client") as mock_client_factory:
            api = MagicMock()
            api.transactions_sync = MagicMock(side_effect=fake_sync)
            mock_client_factory.return_value = api
            from web.plaid.client import get_transactions_sync

            get_transactions_sync("access-sandbox-test")

    opts = captured.get("options")
    assert opts is not None
    ver = getattr(opts, "personal_finance_category_version", None)
    assert ver is not None
    assert getattr(ver, "value", str(ver)) == "v2"
    # /transactions/sync must not include min_last_updated_datetime (UNKNOWN_FIELDS).
    assert getattr(opts, "min_last_updated_datetime", None) is None


def test_get_account_balance_request_includes_min_last_updated():
    """accounts_balance_get receives options.min_last_updated_datetime (Capital One)."""
    from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest

    captured: dict = {}

    def fake_balance(request: AccountsBalanceGetRequest):
        captured["options"] = request.options
        return {"accounts": []}

    with patch("web.plaid.client.get_plaid_client") as mock_client_factory:
        api = MagicMock()
        api.accounts_balance_get = MagicMock(side_effect=fake_balance)
        mock_client_factory.return_value = api
        from web.plaid.client import get_account_balances

        get_account_balances("access-test")

    opts = captured.get("options")
    assert opts is not None
    assert getattr(opts, "min_last_updated_datetime", None) is not None
