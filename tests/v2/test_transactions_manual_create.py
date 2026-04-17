"""Manual / cash transaction create model, delete rules, and cash insert balance."""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from tests.v2.conftest import make_mock_pool
from web.transactions.models import TransactionCreate
from web.transactions.repo import TransactionsRepository


def test_transaction_create_rejects_zero_amount_cents():
    with pytest.raises(ValidationError):
        TransactionCreate(amount_cents=0, date=date(2026, 1, 1), name="x")


def test_transaction_create_accepts_signed_amount():
    m = TransactionCreate(amount_cents=-100, date=date(2026, 1, 1), name="Income")
    assert m.amount_cents == -100


def test_transaction_create_strips_unknown_fields():
    """Client must not set source — extra keys are ignored."""
    m = TransactionCreate.model_validate(
        {
            "amount_cents": 50,
            "date": date(2026, 1, 1),
            "name": "a",
            "source": "plaid",
            "account_id": 99,
        }
    )
    dumped = m.model_dump()
    assert "source" not in dumped
    assert "account_id" not in dumped


class TestTransactionsRepositoryDelete:
    @pytest.fixture
    def repo(self):
        return TransactionsRepository()

    @pytest.mark.asyncio
    async def test_delete_uses_non_plaid_sources(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        txn_cm = MagicMock()
        txn_cm.__aenter__ = AsyncMock(return_value=None)
        txn_cm.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=txn_cm)
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"id": 42, "account_id": 1, "amount_cents": 2500, "source": "cash"},
                {"id": 1},
            ]
        )
        conn.execute = AsyncMock(return_value="DELETE 1")
        with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
            ok = await repo.delete_transaction(42)
        assert ok is True
        delete_sql = conn.execute.call_args_list[-1][0][0]
        assert "DELETE FROM transactions WHERE id = $1" in delete_sql

    @pytest.mark.asyncio
    async def test_delete_cash_reverts_wallet_balance(self, repo):
        """Deleting source=cash runs UPDATE accounts ... + amount_cents before DELETE."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        txn_cm = MagicMock()
        txn_cm.__aenter__ = AsyncMock(return_value=None)
        txn_cm.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=txn_cm)
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"id": 42, "account_id": 9, "amount_cents": -1500, "source": "cash"},
                {"id": 9},
            ]
        )
        conn.execute = AsyncMock(return_value="DELETE 1")
        with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
            ok = await repo.delete_transaction(42)
        assert ok is True
        calls = [c[0] for c in conn.fetchrow.call_args_list]
        assert any("UPDATE accounts" in str(sql) and "current_balance_cents" in str(sql) for sql in calls)


class TestCreateCashTransaction:
    @pytest.fixture
    def repo(self):
        return TransactionsRepository()

    @pytest.mark.asyncio
    async def test_create_cash_updates_balance(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        txn_cm = MagicMock()
        txn_cm.__aenter__ = AsyncMock(return_value=None)
        txn_cm.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=txn_cm)

        inserted = {
            "id": 100,
            "account_id": 7,
            "amount_cents": 1200,
            "source": "cash",
            "currency": "USD",
            "date": date(2026, 4, 1),
            "name": "Coffee",
        }

        conn.fetchrow = AsyncMock(
            side_effect=[
                {"id": 7, "plaid_account_id": None},
                inserted,
                {"id": 7},
            ]
        )

        data = {
            "account_id": 7,
            "amount_cents": 1200,
            "date": date(2026, 4, 1),
            "name": "Coffee",
            "source": "cash",
            "currency": "USD",
            "payment_channel": "other",
            "is_pending": False,
        }
        with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
            out = await repo.create_cash_transaction(data)
        assert out["id"] == 100
        assert out["source"] == "cash"
