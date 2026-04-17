"""Tests for web/recurring/ — price change detection and forecast calculations."""
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.reports.calculations import build_forecast, next_occurrence


class TestNextOccurrence:
    def test_monthly(self):
        assert next_occurrence(date(2026, 3, 15), "MONTHLY") == date(2026, 4, 15)

    def test_weekly(self):
        assert next_occurrence(date(2026, 1, 1), "WEEKLY") == date(2026, 1, 8)

    def test_biweekly(self):
        assert next_occurrence(date(2026, 1, 1), "BIWEEKLY") == date(2026, 1, 15)

    def test_annually(self):
        assert next_occurrence(date(2025, 4, 15), "ANNUALLY") == date(2026, 4, 15)

    def test_unknown(self):
        assert next_occurrence(date(2026, 1, 1), "UNKNOWN") is None

    def test_empty_frequency(self):
        assert next_occurrence(date(2026, 1, 1), "") is None


class TestBuildForecast:
    def _stream(self, last_date, frequency, amount=1000, direction="outflow"):
        return {
            "id": 1,
            "is_active": True,
            "direction": direction,
            "description": "Netflix",
            "merchant_name": "Netflix",
            "frequency": frequency,
            "last_date": last_date,
            "last_amount_cents": amount,
            "average_amount_cents": amount,
            "user_label": None,
        }

    def test_inflow_excluded(self):
        today = date.today()
        stream = self._stream(today - timedelta(days=5), "MONTHLY", direction="inflow")
        assert build_forecast([stream], days=30) == []

    def test_inactive_excluded(self):
        today = date.today()
        stream = self._stream(today - timedelta(days=5), "MONTHLY")
        stream["is_active"] = False
        assert build_forecast([stream], days=30) == []

    def test_entries_sorted_by_date(self):
        today = date.today()
        streams = [
            self._stream(today - timedelta(days=20), "MONTHLY"),
            self._stream(today - timedelta(days=5), "WEEKLY"),
        ]
        entries = build_forecast(streams, days=30)
        dates = [e["date"] for e in entries]
        assert dates == sorted(dates)


class TestRecurringPriceChange:
    @pytest.mark.asyncio
    async def test_get_price_changes_query(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = []

        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            result = await RecurringRepository().get_price_changes()

        assert result == []
        call_args = conn.fetch.call_args
        assert call_args is not None
        # Verify threshold 0.10 is passed as argument
        args = call_args.args
        assert any(isinstance(a, float) and abs(a - 0.10) < 0.001 for a in args)
