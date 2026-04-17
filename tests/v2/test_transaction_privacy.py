"""Unit tests for transaction privacy (is_private) filtering."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.transactions.repo import TransactionsRepository


def _make_row(**kwargs):
    """Build a minimal transaction-like dict for mocking."""
    defaults = {
        "id": 1,
        "account_id": 10,
        "amount_cents": 5000,
        "currency": "USD",
        "date": "2026-04-01",
        "name": "Amazon",
        "source": "plaid",
        "is_private": False,
        "is_pending": False,
        "account_user_id": 42,
    }
    defaults.update(kwargs)
    return MagicMock(**defaults, **{k: v for k, v in defaults.items()})


class TestGetTransactionPrivacy:
    @pytest.fixture
    def repo(self):
        return TransactionsRepository()

    @pytest.mark.asyncio
    async def test_returns_own_private_transaction(self, repo):
        """Owner of a private transaction should always be able to fetch it."""
        row = {
            "id": 5,
            "is_private": True,
            "account_user_id": 42,
            "account_id": 10,
            "amount_cents": 12000,
            "name": "Secret gift",
            "source": "plaid",
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        pool = make_mock_pool(conn)
        with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_transaction(5, viewer_user_id=42)
        assert result is not None
        assert result["id"] == 5

    @pytest.mark.asyncio
    async def test_hides_other_users_private_transaction(self, repo):
        """viewer_user_id that doesn't own the transaction should get None."""
        row = {
            "id": 5,
            "is_private": True,
            "account_user_id": 42,
            "account_id": 10,
            "amount_cents": 12000,
            "name": "Secret gift",
            "source": "plaid",
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        pool = make_mock_pool(conn)
        with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_transaction(5, viewer_user_id=99)
        assert result is None

    @pytest.mark.asyncio
    async def test_public_transaction_visible_to_all(self, repo):
        """is_private=False transactions are returned regardless of viewer."""
        row = {
            "id": 7,
            "is_private": False,
            "account_user_id": 42,
            "account_id": 10,
            "amount_cents": 3000,
            "name": "Coffee",
            "source": "plaid",
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        pool = make_mock_pool(conn)
        with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_transaction(7, viewer_user_id=99)
        assert result is not None
        assert result["id"] == 7

    @pytest.mark.asyncio
    async def test_no_viewer_bypasses_privacy_filter(self, repo):
        """Internal calls without viewer_user_id return even private rows."""
        row = {
            "id": 8,
            "is_private": True,
            "account_user_id": 42,
            "account_id": 10,
            "amount_cents": 9900,
            "name": "Birthday surprise",
            "source": "cash",
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        pool = make_mock_pool(conn)
        with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_transaction(8, viewer_user_id=None)
        assert result is not None
        assert result["id"] == 8


class TestTransactionUpdatePrivacy:
    @pytest.fixture
    def repo(self):
        return TransactionsRepository()

    @pytest.mark.asyncio
    async def test_update_allows_is_private_field(self, repo):
        """update_transaction must accept is_private in the payload."""
        returned_row = MagicMock()
        returned_row.__getitem__ = lambda self, key: {"id": 1, "is_private": True}.get(key)
        returned_row.__contains__ = lambda self, key: key in {"id", "is_private"}

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": 1, "is_private": True, "amount_cents": 500})
        pool = make_mock_pool(conn)
        with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.update_transaction(1, {"is_private": True})
        sql_used = conn.fetchrow.call_args[0][0]
        assert "is_private" in sql_used
        assert result is not None
