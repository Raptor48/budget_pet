"""Tests for the `parent_category_id` filter on GET /api/transactions.

The Reports → By Category drill-down calls the transactions list with
`parent_category_id=<primary_id>` so that the drill-in (a) picks up
transactions categorized on the primary row itself AND (b) picks up
transactions categorized on any PFC-detailed child linked via
`categories.parent_id`. This mirrors the COALESCE(parent_id, category_id)
bucket rule used in /api/reports/by-category.
"""
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.transactions.repo import TransactionsRepository


@pytest.mark.asyncio
async def test_parent_category_id_rolls_primary_plus_children():
    """`parent_category_id=<pid>` expands to a categories subquery that
    covers both the primary id itself and any row with `parent_id = pid`.
    The split-side EXISTS clause applies the same rule so rows split to a
    detailed child of the primary still match."""
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetch = AsyncMock(return_value=[])

    repo = TransactionsRepository()
    with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
        await repo.list_transactions(parent_category_id=42)

    sql = conn.fetch.await_args.args[0]
    args = list(conn.fetch.await_args.args[1:])

    # Primary + child subquery on the transaction itself
    assert (
        "t.category_id IN (SELECT id FROM categories WHERE id = $1 OR parent_id = $1)"
        in sql
    )
    # Split-aware: EXISTS clause mirrors the same subquery on splits
    assert "FROM transaction_splits ts" in sql
    assert (
        "ts.category_id IN (SELECT id FROM categories WHERE id = $1 OR parent_id = $1)"
        in sql
    )
    # Only one `parent_category_id` bind; placeholder reused three times in SQL.
    assert args[0] == 42


@pytest.mark.asyncio
async def test_parent_category_id_not_applied_by_default():
    """Backward compat: without `parent_category_id` the new subquery does
    not appear (legacy clients / plain /api/transactions calls still
    behave as before)."""
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetch = AsyncMock(return_value=[])

    repo = TransactionsRepository()
    with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
        await repo.list_transactions()

    sql = conn.fetch.await_args.args[0]
    assert "SELECT id FROM categories WHERE id" not in sql


@pytest.mark.asyncio
async def test_category_id_and_parent_category_id_can_coexist_in_sql():
    """Both filters can be passed; each produces its own WHERE clause with
    its own placeholder. Callers are expected to use one at a time, but
    the repo tolerates both (useful for future UIs like "this primary +
    also this specific row")."""
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetch = AsyncMock(return_value=[])

    repo = TransactionsRepository()
    with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
        await repo.list_transactions(category_id=7, parent_category_id=42)

    sql = conn.fetch.await_args.args[0]
    # Plain equality from `category_id`
    assert "t.category_id = $" in sql
    # Roll-up subquery from `parent_category_id`
    assert "SELECT id FROM categories WHERE id = $" in sql
