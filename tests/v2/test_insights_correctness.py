"""
Phase-1 correctness tests for the Insights feed and its dependencies.

Covers:
- ``cash_flow_mom`` compares equal MTD windows instead of partial-vs-full months.
- ``top_category`` ignores categories with non-positive totals (refund-heavy).
- ``build_forecast`` excludes TOMBSTONED streams.
- ``build_insights_feed`` forwards ``viewer_user_id`` to Recurring repo.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from web.insights.feed import build_insights_feed
from web.reports.calculations import build_forecast


class _ReportsSpy:
    """Minimal reports spy. Records arguments for each method call."""

    def __init__(self, by_category_rows):
        self._by_category_rows = by_category_rows
        self.windows_called: list[tuple[date, date]] = []

    async def get_financial_health_data(self, viewer_user_id=None):
        return {
            "total_debt_cents": 0,
            "mortgage_loan_cents": 0,
            "annual_income_cents": 120_000,
            "monthly_income_cents": 10_000,
            "monthly_expenses_cents": 5_000,
            "total_credit_limit_cents": 50_000,
            "total_credit_balance_cents": 2_000,
            "liquid_balance_cents": 20_000,
            "avg_monthly_expenses_cents": 5_000,
            "has_overdue": False,
        }

    async def get_cash_flow_window(self, start_date, end_date, viewer_user_id=None):
        self.windows_called.append((start_date, end_date))
        # Return a net so the test can assert delta is zero -> info (not warn).
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "income_cents": 100_000,
            "expenses_cents": 60_000,
            "internal_transfer_cents": 0,
            "net_cents": 40_000,
        }

    async def get_by_category(self, _month, viewer_user_id=None, rollup="primary", parent_category_id=None):
        return list(self._by_category_rows)

    async def get_category_rolling(self, _month, months=3, viewer_user_id=None):
        return []


class _RecurringSpy:
    def __init__(self):
        self.list_streams_viewer = "unset"
        self.get_price_changes_viewer = "unset"

    async def list_streams(self, direction=None, active_only=True, viewer_user_id=None):
        self.list_streams_viewer = viewer_user_id
        return []

    async def get_price_changes(self, viewer_user_id=None):
        self.get_price_changes_viewer = viewer_user_id
        return []


class _AccountsStub:
    async def list_accounts(self, active_only: bool = True):
        return []


class _BudgetsStub:
    async def get_progress(self, _month: str, viewer_user_id=None):
        return []


def _install_repo_stubs(monkeypatch, *, reports, recurring):
    monkeypatch.setattr("web.reports.repo.ReportsRepository", lambda: reports)
    monkeypatch.setattr("web.recurring.repo.RecurringRepository", lambda: recurring)
    monkeypatch.setattr("web.accounts.repo.AccountsRepository", lambda: _AccountsStub())
    monkeypatch.setattr("web.budgets.repo.BudgetsRepository", lambda: _BudgetsStub())


@pytest.mark.asyncio
async def test_cash_flow_mom_uses_equal_mtd_windows(monkeypatch):
    spy = _ReportsSpy(by_category_rows=[])
    _install_repo_stubs(monkeypatch, reports=spy, recurring=_RecurringSpy())

    await build_insights_feed()

    assert len(spy.windows_called) == 2, "both current and prior windows must be queried"
    cur_start, cur_end = spy.windows_called[0]
    prev_start, prev_end = spy.windows_called[1]

    today = date.today()
    assert cur_start == today.replace(day=1)
    assert cur_end == today

    # Prior window starts on day 1 of the previous month and ends at the
    # same day-of-month as today (clamped to the prior month's length).
    expected_prev_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    assert prev_start == expected_prev_start

    # End day is same as today.day (or clamped to prior month's last day).
    import calendar

    prev_days = calendar.monthrange(expected_prev_start.year, expected_prev_start.month)[1]
    expected_prev_end_day = min(today.day, prev_days)
    assert prev_end.day == expected_prev_end_day
    assert prev_end.month == expected_prev_start.month


@pytest.mark.asyncio
async def test_top_category_ignores_refund_heavy_negatives(monkeypatch):
    """If every category net is <= 0 (huge refund month), no top_category card."""
    rows = [
        {"category_name": "Groceries", "amount_cents": -5000},
        {"category_name": "Dining", "amount_cents": -200},
    ]
    spy = _ReportsSpy(by_category_rows=rows)
    _install_repo_stubs(monkeypatch, reports=spy, recurring=_RecurringSpy())

    out = await build_insights_feed()
    types = {c["type"] for c in out["cards"]}
    assert "top_category" not in types


@pytest.mark.asyncio
async def test_top_category_picks_real_top_despite_mixed_refunds(monkeypatch):
    """A category with net 0 must not be picked over one with real positive spend."""
    rows = [
        {"category_name": "Dining", "amount_cents": -500},
        {"category_name": "Groceries", "amount_cents": 40_000},
        {"category_name": "Fuel", "amount_cents": 20_000},
    ]
    spy = _ReportsSpy(by_category_rows=rows)
    _install_repo_stubs(monkeypatch, reports=spy, recurring=_RecurringSpy())

    out = await build_insights_feed()
    top_cards = [c for c in out["cards"] if c["type"] == "top_category"]
    assert len(top_cards) == 1
    assert top_cards[0]["summary"] == "Groceries"


@pytest.mark.asyncio
async def test_build_insights_feed_forwards_viewer_to_recurring(monkeypatch):
    spy = _ReportsSpy(by_category_rows=[])
    rec = _RecurringSpy()
    _install_repo_stubs(monkeypatch, reports=spy, recurring=rec)

    await build_insights_feed(viewer_user_id=77)

    assert rec.list_streams_viewer == 77
    assert rec.get_price_changes_viewer == 77


def test_build_forecast_skips_tombstoned():
    today = date.today()
    last = (today - timedelta(days=3)).isoformat()
    streams = [
        {
            "id": 1,
            "is_active": True,
            "direction": "outflow",
            "last_date": last,
            "frequency": "WEEKLY",
            "last_amount_cents": 1000,
            "average_amount_cents": 1000,
            "status": "TOMBSTONED",
            "description": "Stopped stream",
        },
        {
            "id": 2,
            "is_active": True,
            "direction": "outflow",
            "last_date": last,
            "frequency": "WEEKLY",
            "last_amount_cents": 2000,
            "average_amount_cents": 2000,
            "status": "MATURE",
            "description": "Still active",
        },
    ]
    entries = build_forecast(streams, days=14)
    ids = [e["stream_id"] for e in entries]
    assert 1 not in ids, "TOMBSTONED streams must not appear in forecast"
    assert 2 in ids


def test_build_forecast_lower_case_status_also_skipped():
    today = date.today()
    last = (today - timedelta(days=3)).isoformat()
    streams = [
        {
            "id": 1,
            "is_active": True,
            "direction": "outflow",
            "last_date": last,
            "frequency": "WEEKLY",
            "last_amount_cents": 1000,
            "average_amount_cents": 1000,
            "status": "tombstoned",
            "description": "Stopped stream",
        },
    ]
    assert build_forecast(streams, days=14) == []
