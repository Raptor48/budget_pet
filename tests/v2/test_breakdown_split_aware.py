"""
Regression tests for split-aware income/expense breakdowns.

Before V2.3 hot-fix, ``get_income_breakdown`` and ``get_expense_breakdown``
summed ``t.amount_cents`` on the parent and ignored ``transaction_splits``.
That made the per-category numbers in the Income/Expenses tab disagree with
``get_by_category`` (which has been split-aware for a while). The fix is the
same UNION ALL pattern used by ``get_by_category`` / ``get_progress``.

These tests assert the SQL the repo emits is split-aware (UNION ALL across
``transactions`` + ``transaction_splits``) and that the gross-outflow
``internal_transfer_cents`` makes it into the SQL string. They are
SQL-shape tests rather than integration tests because the real
multi-row aggregation requires a Postgres pool the v2 mock-conn harness
intentionally avoids.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.reports.repo import ReportsRepository


class TestIncomeBreakdownSplitAware:
    @pytest.mark.asyncio
    async def test_sql_is_split_aware(self):
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
            await repo.get_income_breakdown("2026-04")

        sql = captured["sql"]
        assert "WITH actual AS" in sql, "income breakdown must use the UNION-ALL CTE"
        assert "UNION ALL" in sql
        assert "FROM transaction_splits" in sql
        assert "NOT EXISTS (SELECT 1 FROM transaction_splits ts" in sql
        assert "transaction_class = 'income'" in sql

    @pytest.mark.asyncio
    async def test_signs_remain_flipped_for_income(self):
        """Income amounts come out positive (Plaid stores them as negative
        cents). The repo's SUM must flip the sign — ``-actual.amount_cents``
        — so the public response is always non-negative."""
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

        assert "SUM(-actual.amount_cents)" in captured["sql"]


class TestExpenseBreakdownSplitAware:
    @pytest.mark.asyncio
    async def test_sql_is_split_aware(self):
        repo = ReportsRepository()
        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetch(sql, *args, **kwargs):
            captured["sql"] = sql
            return []

        conn.fetch = fake_fetch
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_expense_breakdown("2026-04")

        sql = captured["sql"]
        assert "WITH actual AS" in sql
        assert "UNION ALL" in sql
        assert "FROM transaction_splits" in sql
        assert "NOT EXISTS (SELECT 1 FROM transaction_splits ts" in sql
        assert "transaction_class = 'expense'" in sql
        # Refunds must still net inside the category bucket.
        assert "amount_cents > 0" not in sql
        # HAVING filter on net != 0 stays in place.
        assert "HAVING SUM(actual.amount_cents) <> 0" in sql

    @pytest.mark.asyncio
    async def test_signs_unchanged_for_expense(self):
        """Expenses arrive positive, so the breakdown must NOT flip — that
        would turn refunds into negative income. ``SUM(actual.amount_cents)``,
        no minus sign."""
        repo = ReportsRepository()
        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetch(sql, *args, **kwargs):
            captured["sql"] = sql
            return []

        conn.fetch = fake_fetch
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_expense_breakdown("2026-04")

        assert "SUM(actual.amount_cents)" in captured["sql"]
        assert "SUM(-actual.amount_cents)" not in captured["sql"]


class TestInternalTransferGross:
    """``internal_transfer_cents`` is documented (CashFlowMonth) as the
    *absolute outflow-side total*. Pre-fix the SQL summed signed amounts,
    which netted to ~0 on every cents-exact pair — hiding meaningful
    movement. The fix uses ``GREATEST(amount_cents, 0)`` so the value is
    the gross outgoing leg.
    """

    @pytest.mark.asyncio
    async def test_cash_flow_uses_gross_outflow(self):
        repo = ReportsRepository()
        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetchrow(sql, *args, **kwargs):
            captured["sql"] = sql
            return {
                "income_cents": 0,
                "expenses_cents": 0,
                "internal_transfer_cents": 0,
            }

        conn.fetchrow = fake_fetchrow
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_cash_flow("2026-04")

        sql = captured["sql"]
        assert (
            "GREATEST(t.amount_cents, 0)" in sql
        ), "internal_transfer_cents must be the gross outflow side"
        # Sanity: we did NOT touch the income/expense sums.
        assert "SUM(CASE WHEN t.transaction_class = 'income' THEN -t.amount_cents" in sql
        assert "SUM(CASE WHEN t.transaction_class = 'expense' THEN t.amount_cents" in sql

    @pytest.mark.asyncio
    async def test_cash_flow_history_uses_gross_outflow(self):
        repo = ReportsRepository()
        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetch(sql, *args, **kwargs):
            captured["sql"] = sql
            return []

        conn.fetch = fake_fetch
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_cash_flow_history(months=12)

        assert "GREATEST(t.amount_cents, 0)" in captured["sql"]


class TestFinancialHealthAvgFix:
    """``get_financial_health_data`` previously did ``AVG(monthly_total)``
    over a GROUP BY month subquery, which silently divided by the number of
    *non-empty* months. A user with a one-month gap saw the score jump
    instead of the gap dragging the average down. The fix uses a fixed
    denominator (3 for monthly_*, 6 for avg_expenses) — what the
    docstring promised all along.
    """

    @pytest.mark.asyncio
    async def test_uses_fixed_denominator(self):
        repo = ReportsRepository()
        captured: list[str] = []
        conn = AsyncMock()

        async def fake_fetchval(sql, *args, **kwargs):
            captured.append(sql)
            return 0

        conn.fetchval = fake_fetchval
        pool = make_mock_pool(conn)

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_financial_health_data()

        joined = "\n".join(captured)
        # AVG over a GROUP BY m subquery is the bug we removed.
        assert "AVG(monthly_total)" not in joined
        # The 3-month aggregates divide by 3.0; the 6-month one by 6.0.
        assert "SUM(-amount_cents) / 3.0" in joined  # monthly_income
        assert "SUM(amount_cents) / 3.0" in joined   # monthly_expenses
        assert "SUM(amount_cents) / 6.0" in joined   # avg_expenses
