"""Per-user Cash wallet provisioning."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.accounts.repo import AccountsRepository


@pytest.mark.asyncio
async def test_ensure_cash_wallet_creates_then_reuses():
    repo = AccountsRepository()
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    txn_cm = MagicMock()
    txn_cm.__aenter__ = AsyncMock(return_value=None)
    txn_cm.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_cm)

    full_row = {
        "id": 3,
        "name": "Cash",
        "type": "depository",
        "subtype": "cash",
        "plaid_account_id": None,
        "plaid_item_id": None,
        "user_id": 9,
        "is_active": True,
        "current_balance_cents": 0,
        "currency": "USD",
        "institution_logo": None,
        "institution_color": None,
        "owner_username": "u",
        "created_at": None,
        "updated_at": None,
        "mask": None,
        "official_name": None,
        "available_balance_cents": None,
        "credit_limit_cents": None,
        "apr_percent": None,
        "min_payment_cents": None,
        "due_day": None,
        "is_overdue": None,
        "last_payment_date": None,
        "last_statement_balance_cents": None,
        "expected_payoff_date": None,
        "ytd_interest_paid_cents": None,
        "holder_category": None,
        "last_synced_at": None,
    }

    conn.fetchrow = AsyncMock(
        side_effect=[
            None,
            {"id": 3},
            full_row,
            {"id": 3},
            full_row,
        ]
    )
    conn.execute = AsyncMock()

    with patch("web.accounts.repo.get_pool", AsyncMock(return_value=pool)):
        first = await repo.ensure_cash_wallet(9)
        second = await repo.ensure_cash_wallet(9)

    assert first["id"] == 3
    assert second["id"] == 3
    assert first["is_cash_wallet"] is True
    assert second["is_cash_wallet"] is True
