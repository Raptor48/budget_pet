"""Regression tests for category hierarchy behaviour across reports, budgets,
and category resolution.

These are unit tests with a mocked asyncpg pool. They verify:

1. `reports.get_by_category(rollup='primary')` emits a SQL grouping on
   `COALESCE(parent_id, category_id)` and sets `bucket_key='p:*'`.
2. `reports.get_by_category(rollup='detailed', parent_category_id=X)` scopes
   the query to children of X (filters both the direct path and the
   transaction_splits branch).
3. `budgets.create_budget` rejects a child budget when a parent budget exists
   for the same month.
4. `budgets.create_budget` rejects a parent budget when any child already has
   a budget for the same month.
5. `budgets.create_budget` accepts a bare (top-level custom) category without
   hierarchy conflicts.

DB SQL execution itself is covered by integration tests; these unit tests lock
in the *contracts* each call relies on.
"""
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool


# ---------------------------------------------------------------------------
# Reports — rollup behaviour
# ---------------------------------------------------------------------------


class TestReportsRollup:
    @pytest.mark.asyncio
    async def test_primary_rollup_uses_parent_aggregation(self):
        from web.reports.repo import ReportsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = []
        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await ReportsRepository().get_by_category("2026-04")

        sql = conn.fetch.call_args.args[0]
        assert "COALESCE(parent_id, category_id)" in sql, (
            "Primary rollup must aggregate detailed children under parent_id"
        )
        assert "'p:'" in sql, "Primary rollup must stamp bucket_key with 'p:'"

    @pytest.mark.asyncio
    async def test_detailed_rollup_emits_child_bucket_keys(self):
        from web.reports.repo import ReportsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = []
        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await ReportsRepository().get_by_category("2026-04", rollup="detailed")

        sql = conn.fetch.call_args.args[0]
        assert "'c:'" in sql, "Detailed rollup must stamp bucket_key with 'c:'"
        # Should NOT roll up into parent:
        assert "COALESCE(parent_id, category_id)" not in sql

    @pytest.mark.asyncio
    async def test_detailed_rollup_scopes_to_parent_category_id(self):
        from web.reports.repo import ReportsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = []
        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await ReportsRepository().get_by_category(
                "2026-04", rollup="detailed", parent_category_id=11
            )

        args = conn.fetch.call_args.args
        sql = args[0]
        # parent_category_id must become a positional argument and fuel both
        # the transactions and splits branch filters.
        assert 11 in args
        assert "WHERE parent_id =" in sql or "parent_id = $" in sql


# ---------------------------------------------------------------------------
# Budgets — parent/child conflict validation
# ---------------------------------------------------------------------------


class TestBudgetsHierarchyGuards:
    @pytest.mark.asyncio
    async def test_child_budget_rejected_when_parent_exists(self):
        from web.budgets.repo import BudgetsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.side_effect = [
            # Category lookup: child with parent_id=9
            {"id": 42, "parent_id": 9},
            # Parent budget exists for same month
            {"1": 1},
        ]
        with patch("web.budgets.repo.get_pool", AsyncMock(return_value=pool)):
            with pytest.raises(ValueError, match="parent-category budget already exists"):
                await BudgetsRepository().create_budget(
                    {"category_id": 42, "month": "2026-04", "budget_cents": 10000}
                )

    @pytest.mark.asyncio
    async def test_parent_budget_rejected_when_child_exists(self):
        from web.budgets.repo import BudgetsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.side_effect = [
            # Category lookup: parent (no parent_id)
            {"id": 9, "parent_id": None},
            # Some child budget exists
            {"1": 1},
        ]
        with patch("web.budgets.repo.get_pool", AsyncMock(return_value=pool)):
            with pytest.raises(ValueError, match="child budget already exists"):
                await BudgetsRepository().create_budget(
                    {"category_id": 9, "month": "2026-04", "budget_cents": 10000}
                )

    @pytest.mark.asyncio
    async def test_top_level_custom_category_no_conflict(self):
        """A top-level custom category with no children and no sibling budgets
        must insert without conflict."""
        from web.budgets.repo import BudgetsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.side_effect = [
            # Category lookup
            {"id": 5, "parent_id": None},
            # No child budgets
            None,
            # INSERT ... RETURNING result
            {"id": 1, "category_id": 5, "month": "2026-04", "budget_cents": 10000},
        ]
        with patch("web.budgets.repo.get_pool", AsyncMock(return_value=pool)):
            row = await BudgetsRepository().create_budget(
                {"category_id": 5, "month": "2026-04", "budget_cents": 10000}
            )
        assert row["category_id"] == 5

    @pytest.mark.asyncio
    async def test_unknown_category_rejected(self):
        from web.budgets.repo import BudgetsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.side_effect = [None]  # category not found
        with patch("web.budgets.repo.get_pool", AsyncMock(return_value=pool)):
            with pytest.raises(ValueError, match="Category not found"):
                await BudgetsRepository().create_budget(
                    {"category_id": 999, "month": "2026-04", "budget_cents": 1}
                )
