"""Tests for web/transactions/splits_repo.py — split invariant enforcement."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.transactions.splits_repo import SplitsRepository


class TestSplitsRepository:
    @pytest.fixture
    def repo(self):
        return SplitsRepository()

    @pytest.mark.asyncio
    async def test_set_splits_validates_invariant(self, repo):
        """set_splits raises ValueError when split total != parent amount."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.return_value = {"amount_cents": 5000}

        splits = [
            {"amount_cents": 3000, "category_id": 1},
            {"amount_cents": 1000, "category_id": 2},  # total = 4000 != 5000
        ]

        with patch("web.transactions.splits_repo.get_pool", AsyncMock(return_value=pool)):
            with pytest.raises(ValueError, match="does not match"):
                await repo.set_splits(transaction_id=1, splits=splits)

    @pytest.mark.asyncio
    async def test_set_splits_accepts_valid(self, repo):
        """set_splits succeeds when splits sum == parent amount."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        # parent fetch + 2 insert fetchrows
        conn.fetchrow.side_effect = [
            {"amount_cents": 5000},
            {"id": 1, "parent_transaction_id": 1, "category_id": 1, "tag_id": None,
             "amount_cents": 3000, "note": None, "created_at": "2026-01-01"},
            {"id": 2, "parent_transaction_id": 1, "category_id": 2, "tag_id": None,
             "amount_cents": 2000, "note": None, "created_at": "2026-01-01"},
        ]

        # transaction context manager
        tx_ctx = MagicMock()
        tx_ctx.__aenter__ = AsyncMock()
        tx_ctx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx_ctx)
        conn.execute = AsyncMock()

        splits = [
            {"amount_cents": 3000, "category_id": 1},
            {"amount_cents": 2000, "category_id": 2},
        ]

        with patch("web.transactions.splits_repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.set_splits(transaction_id=1, splits=splits)

        assert len(result) == 2
        assert sum(s["amount_cents"] for s in result) == 5000

    @pytest.mark.asyncio
    async def test_set_splits_raises_when_not_found(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.return_value = None  # transaction not found

        with patch("web.transactions.splits_repo.get_pool", AsyncMock(return_value=pool)):
            with pytest.raises(ValueError, match="Transaction not found"):
                await repo.set_splits(transaction_id=999, splits=[{"amount_cents": 100}])
