"""Tests for web/recurring/ — price change detection and forecast calculations."""
from datetime import date, timedelta
from decimal import Decimal
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


def _minimal_stream_row(**overrides):
    base = {
        "plaid_stream_id": "p",
        "account_id": 1,
        "direction": "outflow",
        "description": "X",
        "merchant_name": None,
        "average_amount_cents": 1000,
        "last_amount_cents": 1000,
        "currency": "USD",
        "pfc_primary": None,
        "pfc_detailed": None,
        "first_date": None,
        "is_active": True,
        "status": "MATURE",
        "category_id": None,
        "user_label": None,
        "price_change_pct": None,
        "last_synced_at": None,
        "stream_source": "plaid",
        "account_name": "Acct",
        "account_mask": "1111",
        "owner_username": "u1",
        "category_parent_id": None,
        "primary_category_id": None,
        "primary_category_name": None,
        "primary_category_color": None,
    }
    base.update(overrides)
    return base


class TestListStreamsSortedByNextPayment:
    """``list_streams`` orders by soonest ``next_occurrence(last_date, frequency)``."""

    @pytest.mark.asyncio
    async def test_sorts_by_next_payment_not_db_order(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        # DB returns id order 10, 20, 30 — expected next dates: weekly Apr 18→Apr 25,
        # monthly Apr 1→May 1, monthly Apr 10→May 10 → sorted 20, 30, 10.
        conn.fetch.return_value = [
            _minimal_stream_row(
                id=10,
                last_date=date(2026, 4, 10),
                frequency="MONTHLY",
                description="A",
            ),
            _minimal_stream_row(
                id=20,
                last_date=date(2026, 4, 18),
                frequency="WEEKLY",
                description="B",
            ),
            _minimal_stream_row(
                id=30,
                last_date=date(2026, 4, 1),
                frequency="MONTHLY",
                description="C",
            ),
        ]
        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            rows = await RecurringRepository().list_streams()

        assert [r["id"] for r in rows] == [20, 30, 10]


class TestListStreamsEnrichment:
    """`list_streams` must JOIN accounts/users/categories and populate the
    enrichment fields the UI depends on (AccountChip, primary Category column,
    normalized display_title)."""

    @pytest.mark.asyncio
    async def test_enriches_with_account_and_primary_category(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = [
            {
                "id": 1,
                "plaid_stream_id": "abc",
                "account_id": 42,
                "direction": "outflow",
                "description": "NFLX.COM 4029 LOS GATOS CA",
                "merchant_name": "Netflix",
                "frequency": "MONTHLY",
                "average_amount_cents": -1549,
                "last_amount_cents": -2299,
                "currency": "USD",
                "pfc_primary": "ENTERTAINMENT",
                "pfc_detailed": "ENTERTAINMENT_TV_AND_MOVIES",
                "first_date": None,
                "last_date": None,
                "is_active": True,
                "status": "MATURE",
                "category_id": 12,
                "user_label": None,
                "price_change_pct": Decimal("48.42"),
                "last_synced_at": None,
                "stream_source": "plaid",
                "account_name": "Chase Sapphire",
                "account_mask": "4242",
                "owner_username": "denis",
                "category_parent_id": 5,
                "primary_category_id": 5,
                "primary_category_name": "Entertainment",
                "primary_category_color": "#9333ea",
            }
        ]
        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            rows = await RecurringRepository().list_streams()

        assert len(rows) == 1
        r = rows[0]
        assert r["account_name"] == "Chase Sapphire"
        assert r["account_mask"] == "4242"
        assert r["owner_username"] == "denis"
        assert r["primary_category_id"] == 5
        assert r["primary_category_name"] == "Entertainment"
        assert r["primary_category_color"] == "#9333ea"
        assert r["display_title"] == "Netflix"
        assert "category_parent_id" not in r


class TestUpsertSignedPriceChangePct:
    """`price_change_pct` must be signed so the UI can colour drops vs hikes."""

    @pytest.mark.asyncio
    async def test_price_decrease_is_negative(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            await RecurringRepository().upsert_streams(
                [
                    {
                        "stream_id": "abc",
                        "account_id": "plaid_acct_1",
                        "description": "Adobe CC",
                        "average_amount": {"amount": 29.02, "iso_currency_code": "USD"},
                        "last_amount": {"amount": 21.76, "iso_currency_code": "USD"},
                        "frequency": "MONTHLY",
                        "is_active": True,
                    }
                ],
                direction="outflow",
                account_id_map={"plaid_acct_1": 42},
            )

        execute_call = conn.execute.call_args
        assert execute_call is not None
        pct_arg = execute_call.args[16]
        assert pct_arg is not None and pct_arg < 0, (
            f"expected negative signed pct for a price drop, got {pct_arg}"
        )
        assert abs(pct_arg + 25.02) < 0.1  # ~(21.76 - 29.02) / 29.02 * 100

    @pytest.mark.asyncio
    async def test_price_increase_is_positive(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            await RecurringRepository().upsert_streams(
                [
                    {
                        "stream_id": "xyz",
                        "account_id": "plaid_acct_1",
                        "description": "Netflix",
                        "average_amount": {"amount": 15.49, "iso_currency_code": "USD"},
                        "last_amount": {"amount": 22.99, "iso_currency_code": "USD"},
                        "frequency": "MONTHLY",
                        "is_active": True,
                    }
                ],
                direction="outflow",
                account_id_map={"plaid_acct_1": 42},
            )

        pct_arg = conn.execute.call_args.args[16]
        assert pct_arg is not None and pct_arg > 0
        assert abs(pct_arg - 48.42) < 0.1  # ~(22.99 - 15.49) / 15.49 * 100
