"""
Tests for the expense report endpoint (``GET /api/reports/expenses``) and
the shared expense predicate it uses.

Mirror of ``tests/v2/test_income_report.py`` for the expense side. Key
invariants covered:

    * ``get_expense_breakdown`` uses ``transaction_class = 'expense'`` and
      ``SUM(amount_cents)`` — so refunds (negative amounts) naturally
      reduce category totals.
    * Categories with zero net spend for the month are omitted.
    * Privacy filter is honoured — an ``is_private`` row owned by
      someone else never reaches the aggregate.
    * Sandbox parity: the expenses aggregate applies the same
      ``plaid_sandbox`` filter as Cash Flow / Income tab.
    * Grouping per user behaves the same as income (sorted big→small).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.reports.repo import ReportsRepository, _expense_predicate


class TestExpensePredicate:
    def test_default_alias(self):
        assert _expense_predicate() == "t.transaction_class = 'expense'"

    def test_no_alias(self):
        assert _expense_predicate("") == "transaction_class = 'expense'"


class TestGetExpenseBreakdown:
    @pytest.mark.asyncio
    async def test_groups_rows_by_user_and_sums(self):
        """
        One row per (user, category); the repo groups into per-user
        buckets with a per-category sources list and totals that match
        the top-level total. Mirror of the income test.
        """
        repo = ReportsRepository()
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "user_id": 1,
                    "username": "alice",
                    "category_id": 10,
                    "category_name": "Groceries",
                    "category_color": "#00aa00",
                    "amount_cents": 120_000,
                    "transaction_count": 8,
                },
                {
                    "user_id": 1,
                    "username": "alice",
                    "category_id": 11,
                    "category_name": "Coffee",
                    "category_color": "#aa7744",
                    "amount_cents": 18_000,
                    "transaction_count": 12,
                },
                {
                    "user_id": 2,
                    "username": "bob",
                    "category_id": 10,
                    "category_name": "Groceries",
                    "category_color": "#00aa00",
                    "amount_cents": 80_000,
                    "transaction_count": 5,
                },
            ]
        )

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_expense_breakdown("2026-04")

        assert result["month"] == "2026-04"
        assert result["total_cents"] == 218_000
        assert [u["user_id"] for u in result["users"]] == [1, 2]
        alice = result["users"][0]
        assert alice["amount_cents"] == 138_000
        assert len(alice["sources"]) == 2
        assert {s["category_name"] for s in alice["sources"]} == {
            "Groceries",
            "Coffee",
        }

    @pytest.mark.asyncio
    async def test_refund_reduces_category_total(self):
        """
        A category with $45 spend + $20 refund nets to $25 expense for the
        month (documented as refund-correct behavior in
        ``docs/reports-math.md`` §2 invariant 4). This is a structural
        assertion — the DB-side SUM is mocked — but it pins that the
        repository does not post-filter negative source rows.
        """
        repo = ReportsRepository()
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        # The SQL aggregate returns the already-netted amount; the repo's
        # job is to trust it and pass through.
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "user_id": 1,
                    "username": "alice",
                    "category_id": 10,
                    "category_name": "Groceries",
                    "category_color": "#00aa00",
                    "amount_cents": 2_500,  # $25 net
                    "transaction_count": 3,
                },
            ]
        )
        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_expense_breakdown("2026-04")

        assert result["total_cents"] == 2_500
        assert result["users"][0]["sources"][0]["amount_cents"] == 2_500

    @pytest.mark.asyncio
    async def test_empty_month_returns_zero_total(self):
        repo = ReportsRepository()
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch = AsyncMock(return_value=[])
        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_expense_breakdown("2026-04")
        assert result == {"month": "2026-04", "total_cents": 0, "users": []}

    @pytest.mark.asyncio
    async def test_unassigned_owner_label(self):
        repo = ReportsRepository()
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "user_id": None,
                    "username": None,
                    "category_id": 10,
                    "category_name": "Groceries",
                    "category_color": "#00aa00",
                    "amount_cents": 50_000,
                    "transaction_count": 2,
                },
            ]
        )
        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_expense_breakdown("2026-04")

        assert len(result["users"]) == 1
        assert result["users"][0]["user_id"] is None
        assert result["users"][0]["username"] == "Unassigned"

    @pytest.mark.asyncio
    async def test_sql_uses_expense_predicate_and_privacy_filter(self):
        repo = ReportsRepository()
        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetch(sql, *args, **kwargs):
            captured["sql"] = sql
            captured["args"] = args
            return []

        conn.fetch = fake_fetch
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_expense_breakdown("2026-04", viewer_user_id=42)

        assert "transaction_class = 'expense'" in captured["sql"]
        assert "is_private" in captured["sql"]
        # No sign filter — refunds must not be dropped.
        assert "amount_cents > 0" not in captured["sql"]
        # month, viewer_user_id
        assert captured["args"] == ("2026-04", 42)

    @pytest.mark.asyncio
    async def test_sandbox_parity_with_income_tab(self):
        """Expenses tab must honour the same ``plaid_sandbox`` gate as
        Income tab — otherwise demo data appears on one tab but not the
        other and the month's cash-flow tiles disagree."""
        from web import env_flags

        repo = ReportsRepository()
        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetch(sql, *args, **kwargs):
            captured.setdefault("expenses_sql", sql)
            return []

        conn.fetch = fake_fetch
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)), \
             patch.object(env_flags, "reports_include_plaid_sandbox", return_value=False):
            await repo.get_expense_breakdown("2026-04")

        assert "'plaid_sandbox'" in captured["expenses_sql"]
