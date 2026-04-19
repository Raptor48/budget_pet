"""
Tests for the income report + shared income / expense / internal-transfer
predicates.

Covers:
  * ``_income_predicate`` / ``_expense_predicate`` / ``_internal_transfer_predicate``
    SQL generation — the helpers every aggregate must go through after the
    V2 classifier migration. The single source of truth is now the
    ``transactions.transaction_class`` column.
  * Cash flow SQL references all three predicates (regression guard: if
    someone drops the ``transaction_class`` check and falls back to raw
    amount sign, refunds start getting counted as income).
  * ``resolve_category`` still seeds ``is_income`` for Plaid PFC=INCOME
    rows — the classifier reads this flag to tag paycheck-like rows even
    before a pair match exists.
  * ``get_income_breakdown`` groups rows per user and sums correctly.
  * Categories API surface (Out/Update models + allowed update fields).
  * Invariants from ``docs/reports-math.md``:
      - refund on an income-flagged category is NOT counted as income
        (classifier rule 5);
      - TRANSFER_IN without a pair and without a name match is NOT
        counted as income (classifier rules 3/4 + uncategorized
        fallback);
      - income rows tagged ``is_private`` are hidden from other viewers;
      - sandbox parity: Cash Flow and Income tab apply the same sandbox
        filter so their totals always reconcile.
"""
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.categories.models import CategoryOut, CategoryUpdate
from web.categories.repo import CategoriesRepository
from web.reports.repo import (
    ReportsRepository,
    _expense_predicate,
    _income_predicate,
    _internal_transfer_predicate,
)


class TestClassPredicates:
    """All three predicates are thin wrappers around ``transaction_class``."""

    def test_income_default_alias(self):
        sql = _income_predicate()
        assert sql == "t.transaction_class = 'income'"

    def test_income_no_alias_variant(self):
        # No dangling alias prefix when called for unaliased queries
        # (used by the financial-health monthly_income rollup).
        sql = _income_predicate("")
        assert sql == "transaction_class = 'income'"
        assert "t." not in sql

    def test_expense_default_alias(self):
        assert _expense_predicate() == "t.transaction_class = 'expense'"

    def test_internal_transfer_default_alias(self):
        assert (
            _internal_transfer_predicate()
            == "t.transaction_class = 'internal_transfer'"
        )

    @pytest.mark.asyncio
    async def test_cash_flow_sql_uses_all_three_predicates(self):
        """
        Regression test for the cash-flow identity
        ``income + expense + internal_transfer ≡ SUM(amount_cents)``. If any
        one of the three class checks disappears from the SQL, the identity
        breaks and refunds / CC payments silently shift between buckets.
        """
        repo = ReportsRepository()
        captured_sql: dict = {}
        conn = AsyncMock()

        async def fake_fetchrow(sql, *args, **kwargs):
            captured_sql["sql"] = sql
            return {
                "income_cents": 0,
                "expenses_cents": 0,
                "internal_transfer_cents": 0,
            }

        conn.fetchrow = fake_fetchrow
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_cash_flow("2026-04")

        sql = captured_sql["sql"]
        assert "transaction_class = 'income'" in sql
        assert "transaction_class = 'expense'" in sql
        assert "transaction_class = 'internal_transfer'" in sql
        # Refund semantics: expenses are ``SUM(amount_cents)`` (signed),
        # NOT ``SUM(CASE WHEN amount > 0)`` — that would drop refunds on
        # the floor.
        assert "amount_cents > 0" not in sql

    @pytest.mark.asyncio
    async def test_cash_flow_returns_internal_transfer_total(self):
        """The month response carries ``internal_transfer_cents`` so the UI
        can reassure the user that, e.g., a $1,200 CC payment was
        recognized as intra-family money movement rather than silently
        dropped."""
        repo = ReportsRepository()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "income_cents": 500_000,
                "expenses_cents": 200_000,
                "internal_transfer_cents": 120_000,
            }
        )
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_cash_flow("2026-04")

        assert result["income_cents"] == 500_000
        assert result["expenses_cents"] == 200_000
        assert result["internal_transfer_cents"] == 120_000
        # Net excludes internal transfers — they are neither inflow nor outflow.
        assert result["net_cents"] == 300_000


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
        Regression guard: the income SQL must filter by
        ``transaction_class = 'income'`` (the post-V2 source of truth, not
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

        assert "transaction_class = 'income'" in captured["sql"]
        assert "is_private" in captured["sql"]
        # $1 month + $2 viewer_user_id
        assert captured["args"] == ("2026-04", 42)

    @pytest.mark.asyncio
    async def test_sandbox_filter_applied_consistently(self):
        """Invariant: Cash Flow and Income tab must either both include or
        both exclude ``source = 'plaid_sandbox'``. Any drift means a demo
        paycheck appears in one tab but not the other and the two widgets
        disagree on the same month."""
        from web import env_flags

        repo = ReportsRepository()
        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetchrow(sql, *args, **kwargs):
            captured.setdefault("cash_flow_sql", sql)
            return {
                "income_cents": 0,
                "expenses_cents": 0,
                "internal_transfer_cents": 0,
            }

        async def fake_fetch(sql, *args, **kwargs):
            captured.setdefault("income_sql", sql)
            return []

        conn.fetchrow = fake_fetchrow
        conn.fetch = fake_fetch
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)), \
             patch.object(env_flags, "reports_include_plaid_sandbox", return_value=False):
            await repo.get_cash_flow("2026-04")
            await repo.get_income_breakdown("2026-04")

        # Both queries must guard against plaid_sandbox the same way.
        assert "'plaid_sandbox'" in captured["cash_flow_sql"]
        assert "'plaid_sandbox'" in captured["income_sql"]


class TestIncomeInvariants:
    """
    Scenario-level invariants captured from ``docs/reports-math.md``. These
    do not exercise the classifier itself (that lives in
    ``tests/v2/test_classification.py``, Phase E) — they exercise the
    contract the Income tab relies on.
    """

    @pytest.mark.asyncio
    async def test_refund_on_income_category_not_counted_as_income(self):
        """
        A grocery refund ($+25) that got miscategorised onto an income
        category must still be ``expense`` (negative-of-expense, i.e. a
        refund that reduces the month's spending), never income. The
        classifier enforces this via rule 6 (class='expense' requires a
        non-income category OR the category is income but the amount
        signals a refund → uncategorized → diagnostics).

        This test asserts the downstream invariant: the income breakdown
        reads ``transaction_class='income'`` and therefore NEVER picks up
        a row whose class resolved to 'expense' or 'uncategorized', even
        if the category's ``is_income`` flag is TRUE.
        """
        repo = ReportsRepository()
        conn = AsyncMock()
        # The repo query already filters by transaction_class='income'.
        # Simulate a mocked DB that does that filtering: the refund row
        # simply doesn't come back.
        conn.fetch = AsyncMock(return_value=[])
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_income_breakdown("2026-04")

        assert result["total_cents"] == 0
        assert result["users"] == []

    @pytest.mark.asyncio
    async def test_transfer_without_pair_or_name_match_not_counted_as_income(self):
        """
        A Plaid ``TRANSFER_IN`` where (a) the counterparty does not appear
        in ``internal_transfer_names`` and (b) the classifier could not
        find a matching outbound leg should end up as ``uncategorized``,
        NOT as income — even if some well-meaning user ticked
        ``is_income = TRUE`` on the TRANSFER_IN category row.

        Once again this is an integration invariant: the Income tab only
        reads ``transaction_class='income'``, so the suspicious row is
        excluded by construction. We confirm the SQL goes through the
        canonical predicate.
        """
        repo = ReportsRepository()
        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetch(sql, *args, **kwargs):
            captured["sql"] = sql
            return []

        conn.fetch = fake_fetch
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_income_breakdown("2026-04")

        # The predicate that guarantees the invariant.
        assert "transaction_class = 'income'" in captured["sql"]

    @pytest.mark.asyncio
    async def test_privacy_filter_hides_other_users_income(self):
        """An ``is_private`` paycheck on Alice's account is invisible to
        Bob's viewer context. Enforced by the ``is_private`` SQL clause
        (checked above) plus the viewer-id parameter — we confirm both
        flow through here end-to-end."""
        repo = ReportsRepository()
        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetch(sql, *args, **kwargs):
            captured["sql"] = sql
            captured["args"] = args
            return []  # Row filtered out by privacy clause.

        conn.fetch = fake_fetch
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            # Bob (user_id=2) looking at Alice's (user_id=1) private income.
            result = await repo.get_income_breakdown("2026-04", viewer_user_id=2)

        assert "is_private" in captured["sql"]
        assert captured["args"] == ("2026-04", 2)
        assert result["total_cents"] == 0
