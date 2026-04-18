"""Tests for web.insights.feed.build_insights_feed."""
from datetime import date, timedelta

import pytest

from web.insights.feed import build_insights_feed


class _FakeReports:
    def __init__(self):
        self.last_viewer_user_id = object()  # sentinel to detect default

    async def get_financial_health_data(self, viewer_user_id=None):
        self.last_viewer_user_id = viewer_user_id
        return {
            "total_debt_cents": 0,
            "annual_income_cents": 120_000,
            "monthly_income_cents": 10_000,
            "monthly_expenses_cents": 5_000,
            "total_credit_limit_cents": 50_000,
            "total_credit_balance_cents": 2_000,
            "liquid_balance_cents": 20_000,
            "avg_monthly_expenses_cents": 5_000,
            "has_overdue": False,
        }

    async def get_cash_flow(self, _month: str, viewer_user_id=None):
        self.last_viewer_user_id = viewer_user_id
        return {"net_cents": 100}

    async def get_by_category(self, _month: str, viewer_user_id=None, rollup="primary", parent_category_id=None):
        self.last_viewer_user_id = viewer_user_id
        self.last_rollup = rollup
        return [{"category_name": "Groceries", "amount_cents": 12_345}]


class _FakeRecurring:
    def __init__(self, price_changes=None):
        self._price_changes = price_changes or []

    async def list_streams(self, **_kwargs):
        last = (date.today() - timedelta(days=3)).isoformat()
        return [
            {
                "id": 1,
                "description": "Rent",
                "is_active": True,
                "direction": "outflow",
                "last_date": last,
                "frequency": "WEEKLY",
                "average_amount_cents": 5000,
                "last_amount_cents": 5000,
            }
        ]

    async def get_price_changes(self):
        return list(self._price_changes)


@pytest.mark.asyncio
async def test_build_insights_feed_cards_and_actionable(monkeypatch):
    monkeypatch.setattr("web.reports.repo.ReportsRepository", lambda: _FakeReports())
    monkeypatch.setattr("web.recurring.repo.RecurringRepository", lambda: _FakeRecurring())

    out = await build_insights_feed()

    types = {c["type"] for c in out["cards"]}
    assert "financial_health" in types
    assert "cash_flow_mom" in types
    assert "top_category" in types
    assert "forecast" in types
    assert isinstance(out["actionable_count"], int)
    assert all("severity" in c and "title" in c for c in out["cards"])


@pytest.mark.asyncio
async def test_build_insights_feed_propagates_viewer_user_id(monkeypatch):
    """Viewer id must be forwarded to ReportsRepository so privacy filter applies."""
    fake_reports = _FakeReports()
    monkeypatch.setattr("web.reports.repo.ReportsRepository", lambda: fake_reports)
    monkeypatch.setattr("web.recurring.repo.RecurringRepository", lambda: _FakeRecurring())

    await build_insights_feed(viewer_user_id=42)

    # Last call (get_by_category) should record viewer_user_id=42.
    assert fake_reports.last_viewer_user_id == 42


@pytest.mark.asyncio
async def test_price_change_good_and_warn_cards(monkeypatch):
    """Signed price movements should surface as separate good/warn insight cards
    based on the stream direction."""
    monkeypatch.setattr("web.reports.repo.ReportsRepository", lambda: _FakeReports())
    # Adobe dropped on an outflow (good), Netflix hiked on an outflow (warn)
    streams = [
        {
            "id": 1,
            "description": "Adobe CC",
            "merchant_name": "Adobe",
            "direction": "outflow",
            "price_change_pct": "-25.02",
            "user_label": None,
            "display_title": "Adobe",
        },
        {
            "id": 2,
            "description": "Netflix",
            "merchant_name": "Netflix",
            "direction": "outflow",
            "price_change_pct": "48.42",
            "user_label": None,
            "display_title": "Netflix",
        },
    ]
    monkeypatch.setattr(
        "web.recurring.repo.RecurringRepository",
        lambda: _FakeRecurring(price_changes=streams),
    )

    out = await build_insights_feed()
    types = {c["type"] for c in out["cards"]}
    assert "price_changes_good" in types
    assert "price_changes_warn" in types
    # actionable_count should have incremented from the warn card.
    assert out["actionable_count"] >= 1
