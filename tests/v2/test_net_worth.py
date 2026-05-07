"""Tests for net worth snapshot logic in web/reports/repo.py"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.reports.repo import ReportsRepository


class TestNetWorthSnapshot:
    @pytest.fixture
    def repo(self):
        return ReportsRepository()

    @pytest.mark.asyncio
    async def test_snapshot_inserts_correct_values(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        today = date.today()
        liquid = 500000
        investments = 100000
        debt = 200000
        net = liquid + investments - debt

        conn.fetchval.side_effect = [liquid, investments, debt]
        conn.fetchrow.return_value = {
            "snapshot_date": today,
            "liquid_cents": liquid,
            "investment_cents": investments,
            "debt_cents": debt,
            "net_worth_cents": net,
            "created_at": "2026-01-01T00:00:00",
        }

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.snapshot_net_worth()

        assert result["net_worth_cents"] == net
        assert result["liquid_cents"] == liquid
        assert result["debt_cents"] == debt

    @pytest.mark.asyncio
    async def test_snapshot_handles_null_balances(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        today = date.today()
        conn.fetchval.side_effect = [None, None, None]
        conn.fetchrow.return_value = {
            "snapshot_date": today,
            "liquid_cents": 0,
            "investment_cents": 0,
            "debt_cents": 0,
            "net_worth_cents": 0,
            "created_at": "2026-01-01T00:00:00",
        }

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.snapshot_net_worth()

        assert result["net_worth_cents"] == 0


# ---------------------------------------------------------------------------
# Regression: get_net_worth must tolerate Decimal aggregates
# ---------------------------------------------------------------------------
#
# Postgres SUM(BIGINT) returns NUMERIC; asyncpg surfaces NUMERIC as Decimal.
# The debt-payoff projection block multiplies the trajectory delta by ``30``
# and divides ``debt`` by it — Python forbids implicit ``Decimal * float``
# arithmetic, so any path that left the aggregates as Decimal blew up with
# ``TypeError: unsupported operand type(s) for *: 'decimal.Decimal' and
# 'float'`` once the user had:
#   1. debt > 0
#   2. a trajectory snapshot within tolerance
#   3. net worth rising vs that snapshot
# Cast aggregates to int up front (cents are always whole) — this test
# pins the contract by feeding Decimal in and asserting the call returns.


class TestNetWorthDebtPayoff:
    @pytest.fixture
    def repo(self):
        return ReportsRepository()

    @pytest.mark.asyncio
    async def test_get_net_worth_handles_decimal_aggregates_with_debt_payoff(self, repo):
        """Reproduces the prod 500: Decimal SUM aggregates + debt + rising
        trajectory used to raise TypeError on the ``* 30.0`` multiplier."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        today = date.today()
        snapshot_date = today - timedelta(days=180)

        # Mirror real asyncpg behaviour: SUM(BIGINT) → Decimal, not int.
        conn.fetchval.side_effect = [
            Decimal("500000"),  # liquid
            Decimal("100000"),  # investments
            Decimal("200000"),  # debt > 0 — required to enter the bug path
        ]
        conn.fetch.return_value = []  # no per-account rows
        # Trajectory snapshot: 180 days ago, net was 100k less → rising.
        # snapshot_date returned with ABS()/BETWEEN math so two fetchrows
        # might be requested (mom + 6mo). Return the same row for both;
        # the math only uses the first non-None.
        conn.fetchrow.return_value = {
            "snapshot_date": snapshot_date,
            "net_worth_cents": 300000,
        }

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_net_worth()

        # Sanity: aggregates are coerced to int and the response shape is intact.
        assert isinstance(result["liquid_cents"], int)
        assert isinstance(result["debt_cents"], int)
        assert isinstance(result["net_worth_cents"], int)
        assert result["net_worth_cents"] == 500000 + 100000 - 200000
        # Debt payoff actually computed (didn't blow up): 100k delta over
        # 180 days → ~16.6k/mo → 200k debt / 16.6k ≈ 12 months.
        assert isinstance(result["debt_payoff_months"], int)
        assert 1 <= result["debt_payoff_months"] <= 600

    @pytest.mark.asyncio
    async def test_get_net_worth_no_debt_skips_payoff(self, repo):
        """When debt == 0 the trajectory math is skipped entirely — make
        sure the int() cast doesn't accidentally introduce a None bug
        elsewhere."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        conn.fetchval.side_effect = [
            Decimal("500000"),  # liquid
            Decimal("100000"),  # investments
            Decimal("0"),       # debt == 0 → payoff branch skipped
        ]
        conn.fetch.return_value = []
        conn.fetchrow.return_value = None

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.get_net_worth()

        assert result["debt_cents"] == 0
        assert result["debt_payoff_months"] is None
        assert result["net_worth_cents"] == 600000

    @pytest.mark.asyncio
    async def test_snapshot_net_worth_handles_decimal_aggregates(self, repo):
        """Same Decimal-in trap exists in the writer path — pinning it so a
        future refactor that drops the int() cast can't silently regress."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        today = date.today()
        conn.fetchval.side_effect = [
            Decimal("500000"),
            Decimal("100000"),
            Decimal("200000"),
        ]
        conn.fetchrow.return_value = {
            "snapshot_date": today,
            "liquid_cents": 500000,
            "investment_cents": 100000,
            "debt_cents": 200000,
            "net_worth_cents": 400000,
            "created_at": "2026-01-01T00:00:00",
        }

        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.snapshot_net_worth()

        assert result["net_worth_cents"] == 400000
