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
    """``list_streams`` orders by soonest *future* charge — uses
    ``next_future_occurrence``, so a stream whose ``last_date`` is months
    behind sorts by its next-after-today projection, not by the next step
    after ``last_date`` (which may itself be in the past)."""

    @pytest.mark.asyncio
    async def test_sorts_by_next_payment_not_db_order(self):
        from web.recurring.repo import RecurringRepository

        # All test last_dates are seeded in the future relative to any
        # plausible "today", so a single cadence step is already on/after
        # today and the test's expected ordering doesn't drift over time.
        future_anchor = date.today() + timedelta(days=30)
        # Expected next dates (one step from anchor):
        #   id=10  monthly  → +1mo
        #   id=20  weekly   → +7d   (soonest)
        #   id=30  monthly  → +1mo, but seeded 9 days earlier so it lands
        #                     ahead of id=10 → second.
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = [
            _minimal_stream_row(
                id=10,
                last_date=future_anchor,
                frequency="MONTHLY",
                description="A",
            ),
            _minimal_stream_row(
                id=20,
                last_date=future_anchor,
                frequency="WEEKLY",
                description="B",
            ),
            _minimal_stream_row(
                id=30,
                last_date=future_anchor - timedelta(days=9),
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

    @pytest.mark.asyncio
    async def test_fills_primary_category_name_from_pfc_when_unresolved(self):
        """Same PFC→label rules as ``CategoriesRepository`` when no category JOIN name."""
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = [
            _minimal_stream_row(
                id=1,
                description="DoorDash",
                frequency="MONTHLY",
                last_date=date(2026, 4, 1),
                pfc_primary="FOOD_AND_DRINK",
                pfc_detailed="FOOD_AND_DRINK_RESTAURANTS",
                primary_category_name=None,
                primary_category_id=None,
                primary_category_color=None,
            ),
        ]
        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            rows = await RecurringRepository().list_streams()

        assert len(rows) == 1
        assert rows[0]["primary_category_name"] == "Food & Drink: Restaurants"

    @pytest.mark.asyncio
    async def test_keeps_resolved_primary_category_name_from_join(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = [
            _minimal_stream_row(
                id=2,
                frequency="MONTHLY",
                last_date=date(2026, 4, 1),
                pfc_primary="FOOD_AND_DRINK",
                pfc_detailed="FOOD_AND_DRINK_RESTAURANTS",
                primary_category_id=99,
                primary_category_name="Custom Groceries",
                primary_category_color="#00aa00",
            ),
        ]
        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            rows = await RecurringRepository().list_streams()

        assert rows[0]["primary_category_name"] == "Custom Groceries"


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


class TestUserStatusFilter:
    """``list_streams`` defaults to active+paused, hides cancelled.

    Plaid does not let third-party subscriptions be cancelled via API, so the
    user's ``cancelled`` flag is purely a local archive flag — they should
    not surface in the default tab.
    """

    @pytest.mark.asyncio
    async def test_default_excludes_cancelled(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = []
        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            await RecurringRepository().list_streams()
        sql = conn.fetch.call_args.args[0]
        # Filter is applied as: rs.user_status = ANY($N::text[])
        assert "rs.user_status = ANY(" in sql
        # And the default array is active+paused.
        passed_array = next(
            (a for a in conn.fetch.call_args.args if isinstance(a, list)), None
        )
        assert passed_array == ["active", "paused"]

    @pytest.mark.asyncio
    async def test_explicit_cancelled_status(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = []
        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            await RecurringRepository().list_streams(include_user_statuses=["cancelled"])
        passed_array = next(
            (a for a in conn.fetch.call_args.args if isinstance(a, list)), None
        )
        assert passed_array == ["cancelled"]


class TestPriceChangesSnooze:
    """Snoozed streams must not surface in ``get_price_changes`` (so the
    Insights ``price_changes_warn`` card and the UI top-movers strip both
    quiet down)."""

    @pytest.mark.asyncio
    async def test_query_filters_snoozed_and_cancelled(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = []
        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            await RecurringRepository().get_price_changes()
        sql = conn.fetch.call_args.args[0]
        assert "rs.user_status <> 'cancelled'" in sql
        assert "price_change_snoozed_until" in sql


class TestBulkApply:
    """Bulk endpoint flips local lifecycle for many streams in one call."""

    @pytest.mark.asyncio
    async def test_cancel_stamps_cancelled_at_and_status(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = [{"id": 1}, {"id": 2}]
        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            updated = await RecurringRepository().bulk_apply(
                ids=[1, 2], action="cancel"
            )
        assert updated == 2
        sql = conn.fetch.call_args.args[0]
        assert "user_status  = 'cancelled'" in sql
        assert "cancelled_at = NOW()" in sql

    @pytest.mark.asyncio
    async def test_pause_passes_paused_until_arg(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = [{"id": 1}]
        target = date(2026, 6, 1)
        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            await RecurringRepository().bulk_apply(
                ids=[1], action="pause", paused_until=target
            )
        # paused_until is passed as $2.
        assert target in conn.fetch.call_args.args

    @pytest.mark.asyncio
    async def test_snooze_uses_default_30_days_when_unset(self):
        from web.recurring.repo import RecurringRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = [{"id": 1}]
        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            await RecurringRepository().bulk_apply(
                ids=[1], action="snooze_price_change"
            )
        snooze_until = next(
            (a for a in conn.fetch.call_args.args if isinstance(a, date)), None
        )
        assert snooze_until is not None
        days = (snooze_until - date.today()).days
        assert 29 <= days <= 30

    @pytest.mark.asyncio
    async def test_unknown_action_raises(self):
        from web.recurring.repo import RecurringRepository

        with pytest.raises(ValueError):
            await RecurringRepository().bulk_apply(ids=[1], action="zap")

    @pytest.mark.asyncio
    async def test_empty_ids_returns_zero_without_db(self):
        from web.recurring.repo import RecurringRepository

        # No pool patch — we never reach the DB on empty ids.
        updated = await RecurringRepository().bulk_apply(ids=[], action="cancel")
        assert updated == 0
