"""
Tests for the income report + shared "is_income" predicate.

Covers:
  * `_income_predicate` SQL generation (the helper every income aggregate
    must use — Income tab, Cash Flow, Financial Health).
  * Cash flow SQL embeds the predicate (guards against regressions where a
    future change drops the `is_income` guard and starts counting refunds
    as income again).
  * `resolve_category` / `_ensure_primary_category_id` seed ``is_income``
    for Plaid PFC=INCOME rows and leave everything else alone.
  * `get_income_breakdown` groups rows per user and sums correctly.
  * Categories API surface (Out/Update models + allowed update fields).
"""
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.categories.models import CategoryOut, CategoryUpdate
from web.categories.repo import CategoriesRepository
from web.reports.repo import ReportsRepository, _income_predicate


class TestIncomePredicate:
    def test_default_alias(self):
        sql = _income_predicate()
        assert "t.amount_cents < 0" in sql
        assert "t.category_id" in sql
        assert "_ic.is_income = TRUE" in sql

    def test_no_alias_variant(self):
        sql = _income_predicate("")
        assert "amount_cents < 0" in sql
        # No dangling alias prefix when called for unaliased queries
        # (used by the financial-health monthly_income rollup).
        assert "t.amount_cents" not in sql
        assert "_ic.is_income = TRUE" in sql

    @pytest.mark.asyncio
    async def test_cash_flow_sql_uses_predicate(self):
        """
        Not every negative-amount row is real income (refunds, transfers-in
        miscategorised, ...). This regression test asserts that the
        month-total income SUM always joins against `categories.is_income`.
        """
        repo = ReportsRepository()
        captured_sql: dict = {}
        conn = AsyncMock()

        async def fake_fetchrow(sql, *args, **kwargs):
            captured_sql["sql"] = sql
            return {"income_cents": 0, "expenses_cents": 0}

        conn.fetchrow = fake_fetchrow
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_cash_flow("2026-04")

        assert "is_income" in captured_sql["sql"]


class TestResolveCategoryIsIncome:
    @pytest.mark.asyncio
    async def test_primary_income_row_seeded_true(self):
        """
        New PFC=INCOME parent → auto-flagged as income so freshly-synced
        families immediately get sensible defaults.
        """
        repo = CategoriesRepository()
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.side_effect = [
            None,             # no existing primary row
            {"id": 11},       # primary insert returns id
        ]

        with patch("web.categories.repo.get_pool", AsyncMock(return_value=pool)):
            cid = await repo.resolve_category(None, pfc_primary="INCOME")

        assert cid == 11
        # 2nd fetchrow invocation is the INSERT with the is_income flag. The
        # trailing positional arg carries the True flag for INCOME.
        insert_call = conn.fetchrow.call_args_list[1]
        assert insert_call.args[-1] is True

    @pytest.mark.asyncio
    async def test_primary_non_income_row_seeded_false(self):
        repo = CategoriesRepository()
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.side_effect = [
            None,
            {"id": 12},
        ]

        with patch("web.categories.repo.get_pool", AsyncMock(return_value=pool)):
            cid = await repo.resolve_category(None, pfc_primary="FOOD_AND_DRINK")

        assert cid == 12
        insert_call = conn.fetchrow.call_args_list[1]
        assert insert_call.args[-1] is False

    @pytest.mark.asyncio
    async def test_detailed_income_subcategory_seeded_true(self):
        """
        INCOME_WAGES, INCOME_INTEREST_EARNED, ... must inherit the income
        flag from their parent so the Income tab picks them up without
        manual toggling.
        """
        repo = CategoriesRepository()
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.side_effect = [
            {"id": 11},       # existing primary INCOME row
            None,             # no existing detailed row
            {"id": 77},       # inserted detailed row
        ]

        with patch("web.categories.repo.get_pool", AsyncMock(return_value=pool)):
            cid = await repo.resolve_category(
                pfc_detailed="INCOME_WAGES",
                pfc_primary="INCOME",
            )

        assert cid == 77
        # The 3rd call is the INSERT for the detailed row; last positional
        # arg is the is_income flag.
        insert_call = conn.fetchrow.call_args_list[2]
        assert insert_call.args[-1] is True


class TestCategoriesApi:
    def test_category_out_includes_is_income(self):
        """The API surface must expose the flag so the UI can render it."""
        cat = CategoryOut(
            id=1,
            name="Wages",
            plaid_pfc_primary="INCOME",
            plaid_pfc_detailed="INCOME_WAGES",
            color="#00aa00",
            icon=None,
            pfc_icon_url=None,
            source="plaid_pfc",
            created_at=datetime.utcnow(),
            parent_id=None,
            is_income=True,
        )
        assert cat.is_income is True

    def test_category_out_defaults_is_income_false(self):
        cat = CategoryOut(
            id=2,
            name="Groceries",
            color="#3b82f6",
            source="plaid_pfc",
            created_at=datetime.utcnow(),
        )
        assert cat.is_income is False

    def test_category_update_accepts_is_income(self):
        update = CategoryUpdate(is_income=True)
        assert update.is_income is True

    @pytest.mark.asyncio
    async def test_update_category_allows_is_income(self):
        repo = CategoriesRepository()
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 5,
                "name": "Refund",
                "plaid_pfc_primary": None,
                "plaid_pfc_detailed": None,
                "color": "#3b82f6",
                "icon": None,
                "pfc_icon_url": None,
                "source": "custom",
                "created_at": datetime.utcnow(),
                "parent_id": None,
                "is_income": True,
            }
        )

        with patch("web.categories.repo.get_pool", AsyncMock(return_value=pool)):
            updated = await repo.update_category(5, {"is_income": True})

        assert updated is not None
        assert updated["is_income"] is True
        # The UPDATE must target the is_income column — not silently drop it
        # on the floor (which would happen if `allowed` didn't list it).
        update_sql = conn.fetchrow.call_args.args[0]
        assert "is_income" in update_sql


class TestIncomeBreakdown:
    @pytest.mark.asyncio
    async def test_groups_rows_by_user_and_sums(self):
        """
        Backend returns one row per (user, category). The repo must group
        them into per-user buckets with a sources list and a running total
        that matches the top-level total.
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
                    "category_name": "Wages",
                    "category_color": "#00aa00",
                    "amount_cents": 500_000,
                    "transaction_count": 2,
                },
                {
                    "user_id": 1,
                    "username": "alice",
                    "category_id": 11,
                    "category_name": "Interest",
                    "category_color": "#00aacc",
                    "amount_cents": 2_500,
                    "transaction_count": 1,
                },
                {
                    "user_id": 2,
                    "username": "bob",
                    "category_id": 10,
                    "category_name": "Wages",
                    "category_color": "#00aa00",
                    "amount_cents": 400_000,
                    "transaction_count": 2,
                },
            ]
        )

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_income_breakdown("2026-04")

        assert result["month"] == "2026-04"
        assert result["total_cents"] == 902_500
        # Per-user totals sorted high → low.
        assert [u["user_id"] for u in result["users"]] == [1, 2]
        alice = result["users"][0]
        assert alice["amount_cents"] == 502_500
        assert len(alice["sources"]) == 2
        assert {s["category_name"] for s in alice["sources"]} == {"Wages", "Interest"}

    @pytest.mark.asyncio
    async def test_unassigned_owner_label(self):
        """Accounts with no linked user still contribute; label is 'Unassigned'."""
        repo = ReportsRepository()
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "user_id": None,
                    "username": None,
                    "category_id": 10,
                    "category_name": "Wages",
                    "category_color": "#00aa00",
                    "amount_cents": 100_000,
                    "transaction_count": 1,
                },
            ]
        )

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_income_breakdown("2026-04")

        assert len(result["users"]) == 1
        assert result["users"][0]["user_id"] is None
        assert result["users"][0]["username"] == "Unassigned"

    @pytest.mark.asyncio
    async def test_empty_month_returns_zero_total(self):
        repo = ReportsRepository()
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch = AsyncMock(return_value=[])

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_income_breakdown("2026-04")

        assert result == {
            "month": "2026-04",
            "total_cents": 0,
            "users": [],
        }

    @pytest.mark.asyncio
    async def test_sql_uses_income_predicate_and_private_filter(self):
        """
        Regression guard: the income SQL must filter by `is_income` (not just
        by amount sign) AND honour the viewer-private filter.
        """
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
            await repo.get_income_breakdown("2026-04", viewer_user_id=42)

        assert "is_income" in captured["sql"]
        assert "is_private" in captured["sql"]
        # $1 month + $2 viewer_user_id
        assert captured["args"] == ("2026-04", 42)
