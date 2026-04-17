"""Tests for net worth snapshot logic in web/reports/repo.py"""
from datetime import date
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
