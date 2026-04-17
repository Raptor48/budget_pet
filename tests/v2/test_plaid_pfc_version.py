"""Plaid PFC version helper and client request wiring."""
import os
from unittest.mock import MagicMock, patch

import pytest

from web.plaid.constants import DEFAULT_PLAID_PFC_CATEGORY_VERSION, get_plaid_pfc_category_version


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
