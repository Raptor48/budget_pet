"""Tests for bulk tag/split loading on transaction list (no N+1)."""
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.transactions.repo import TransactionsRepository


@pytest.mark.asyncio
async def test_get_tags_for_transaction_ids_groups_by_transaction():
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetch.return_value = [
        {"transaction_id": 1, "id": 10, "name": "a", "color": "#fff", "created_at": None},
        {"transaction_id": 1, "id": 11, "name": "b", "color": "#000", "created_at": None},
        {"transaction_id": 2, "id": 12, "name": "c", "color": "#111", "created_at": None},
    ]
    repo = TransactionsRepository()
    with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
        out = await repo.get_tags_for_transaction_ids([1, 2])
    assert len(out[1]) == 2
    assert len(out[2]) == 1
    assert out[1][0]["name"] == "a"


@pytest.mark.asyncio
async def test_get_splits_for_transaction_ids_groups_by_parent():
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetch.return_value = [
        {"id": 1, "parent_transaction_id": 5, "amount_cents": 100, "category_id": None, "tag_id": None, "note": None, "created_at": None},
        {"id": 2, "parent_transaction_id": 5, "amount_cents": 200, "category_id": None, "tag_id": None, "note": None, "created_at": None},
        {"id": 3, "parent_transaction_id": 6, "amount_cents": 300, "category_id": None, "tag_id": None, "note": None, "created_at": None},
    ]
    repo = TransactionsRepository()
    with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
        out = await repo.get_splits_for_transaction_ids([5, 6])
    assert len(out[5]) == 2
    assert len(out[6]) == 1
    assert sum(s["amount_cents"] for s in out[5]) == 300
