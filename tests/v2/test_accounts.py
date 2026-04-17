"""Tests for web/accounts/repo.py"""
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.accounts.repo import AccountsRepository


class TestAccountsRepository:
    @pytest.fixture
    def repo(self):
        return AccountsRepository()

    @pytest.mark.asyncio
    async def test_provision_from_plaid_creates_account(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.return_value = None  # no existing account

        plaid_accounts = [{
            "account_id": "test-plaid-id",
            "name": "Checking",
            "official_name": "Chase Checking",
            "mask": "1234",
            "type": "depository",
            "subtype": "checking",
            "balances": {"current": 1234.56, "available": 1000.00, "limit": None, "iso_currency_code": "USD"},
            "holder_category": "personal",
        }]

        with patch("web.accounts.repo.get_pool", AsyncMock(return_value=pool)):
            created = await repo.provision_from_plaid(plaid_accounts, "item-1")

        assert created == 1

    @pytest.mark.asyncio
    async def test_provision_updates_existing(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.side_effect = [
            {"user_id": None},  # plaid_items owner
            {"id": 5},  # existing account row
        ]

        plaid_accounts = [{
            "account_id": "existing-plaid-id",
            "name": "Savings",
            "type": "depository",
            "subtype": "savings",
            "balances": {"current": 500.0, "available": None, "limit": None, "iso_currency_code": "USD"},
        }]

        with patch("web.accounts.repo.get_pool", AsyncMock(return_value=pool)):
            created = await repo.provision_from_plaid(plaid_accounts, "item-1")

        assert created == 0

    @pytest.mark.asyncio
    async def test_provision_skips_empty_plaid_id(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        plaid_accounts = [{"account_id": "", "name": "Bad", "type": "other", "balances": {}}]

        with patch("web.accounts.repo.get_pool", AsyncMock(return_value=pool)):
            created = await repo.provision_from_plaid(plaid_accounts, "item-1")

        assert created == 0
