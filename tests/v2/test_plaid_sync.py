"""Tests for Plaid sync — mocking all Plaid API calls."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.plaid.repo import PlaidRepository


def _make_txn(txn_id: str, account_id: str, amount: float = 12.50):
    txn = MagicMock()
    txn.to_dict.return_value = {
        "transaction_id": txn_id,
        "account_id": account_id,
        "amount": amount,
        "iso_currency_code": "USD",
        "date": "2026-04-15",
        "authorized_date": "2026-04-14",
        "datetime": None,
        "authorized_datetime": None,
        "name": "Test Merchant",
        "merchant_name": "Test",
        "merchant_entity_id": None,
        "logo_url": None,
        "website": None,
        "payment_channel": "online",
        "personal_finance_category": {
            "primary": "FOOD_AND_DRINK",
            "detailed": "FOOD_AND_DRINK_COFFEE",
            "confidence_level": "HIGH",
        },
        "personal_finance_category_icon_url": None,
        "counterparties": [],
        "location": None,
        "payment_meta": None,
        "pending": False,
    }
    return txn


class TestPlaidRepository:
    @pytest.fixture
    def repo(self):
        return PlaidRepository()

    def test_extract_txn_maps_personal_finance_category(self, repo):
        """PFC fields must match Plaid's personal_finance_category object (unchanged contract)."""
        raw = {
            "transaction_id": "t-pfc",
            "account_id": "acct-x",
            "amount": 10.0,
            "iso_currency_code": "USD",
            "date": "2026-04-15",
            "authorized_date": None,
            "datetime": None,
            "authorized_datetime": None,
            "name": "Airline",
            "merchant_name": "Air",
            "merchant_entity_id": None,
            "logo_url": None,
            "website": None,
            "payment_channel": "online",
            "personal_finance_category": {
                "primary": "TRAVEL",
                "detailed": "TRAVEL_FLIGHTS",
                "confidence_level": "VERY_HIGH",
            },
            "personal_finance_category_icon_url": "https://cdn.plaid.com/pfc/travel.png",
            "counterparties": [],
            "location": None,
            "payment_meta": None,
            "pending": False,
        }
        row = repo._extract_txn(raw, account_id=42, source="plaid")
        assert row["pfc_primary"] == "TRAVEL"
        assert row["pfc_detailed"] == "TRAVEL_FLIGHTS"
        assert row["pfc_confidence"] == "VERY_HIGH"
        assert row["pfc_icon_url"] == "https://cdn.plaid.com/pfc/travel.png"

    @pytest.mark.asyncio
    async def test_import_transactions_counts_correctly(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock()

        txns = [_make_txn("txn-1", "acct-1"), _make_txn("txn-2", "acct-1", 5.0)]
        account_id_map = {"acct-1": 1}

        with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)):
            count = await repo.import_transactions(txns, account_id_map, source="plaid")

        assert count == 2

    @pytest.mark.asyncio
    async def test_import_skips_unknown_account(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock()

        txns = [_make_txn("txn-unknown", "unknown-acct")]
        account_id_map = {}

        with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)):
            count = await repo.import_transactions(txns, account_id_map, source="plaid")

        assert count == 0
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_removed_transactions(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute.return_value = "DELETE 2"

        removed = [
            MagicMock(**{"to_dict.return_value": {"transaction_id": "txn-a"}}),
            MagicMock(**{"to_dict.return_value": {"transaction_id": "txn-b"}}),
        ]

        with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)):
            count = await repo.delete_removed_transactions(removed)

        assert count == 2


class TestPlaidSyncScheduler:
    @pytest.mark.asyncio
    async def test_sync_all_items_handles_error_gracefully(self):
        """sync_all_items should catch errors and set status=error for failed items."""
        mock_repo = AsyncMock()
        mock_repo.get_items.return_value = [
            {"item_id": "item-1", "access_token": "token-1", "cursor": None},
        ]
        mock_repo.log_sync = AsyncMock()

        # All Plaid client functions are imported inside sync_all_items,
        # so patch at the source module level
        with patch("web.plaid.repo.get_plaid_repo", return_value=mock_repo), \
             patch("web.plaid.client.get_transactions_sync", side_effect=RuntimeError("API down")), \
             patch("web.plaid.client.get_account_balances", return_value=[]), \
             patch("web.plaid.client.get_liabilities", return_value={"credit": [], "student": [], "mortgage": [], "accounts": []}), \
             patch("web.plaid.client.get_recurring_transactions", return_value={"inflow_streams": [], "outflow_streams": []}), \
             patch("web.plaid.client.get_investment_holdings", return_value={"holdings": [], "securities": []}), \
             patch("web.accounts.repo.AccountsRepository.provision_from_plaid", AsyncMock(return_value=0)), \
             patch("web.categories.repo.CategoriesRepository.resolve_category", AsyncMock(return_value=1)), \
             patch("web.recurring.repo.RecurringRepository.upsert_streams", AsyncMock(return_value=0)), \
             patch("web.investments.repo.InvestmentsRepository.upsert_securities", AsyncMock(return_value=0)), \
             patch("web.reports.repo.ReportsRepository.snapshot_net_worth", AsyncMock(return_value={})):
            mock_repo.build_account_id_map = AsyncMock(return_value={})
            from web.plaid.scheduler import sync_all_items
            results = await sync_all_items()

        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert results[0]["item_id"] == "item-1"
