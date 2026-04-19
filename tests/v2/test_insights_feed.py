"""Tests for web.insights.feed.build_insights_feed."""
from datetime import date, timedelta

import pytest

from web.insights.feed import build_insights_feed


class _FakeReports:
    def __init__(self, *, liquid_cents: int = 10_000_000):
        self.last_viewer_user_id = object()  # sentinel to detect default
        self._liquid_cents = liquid_cents

    async def get_financial_health_data(self, viewer_user_id=None):
        self.last_viewer_user_id = viewer_user_id
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

    async def get_cash_flow_window(self, _start_date, _end_date, viewer_user_id=None):
        self.last_viewer_user_id = viewer_user_id
        return {
            "income_cents": 100,
            "expenses_cents": 0,
            "internal_transfer_cents": 0,
            "net_cents": 100,
        }

    async def get_by_category(self, _month: str, viewer_user_id=None, rollup="primary", parent_category_id=None):
        self.last_viewer_user_id = viewer_user_id
        self.last_rollup = rollup
        return [{"category_name": "Groceries", "amount_cents": 12_345}]

    async def get_category_rolling(self, _month: str, months=3, viewer_user_id=None):
        self.last_viewer_user_id = viewer_user_id
        return []

    async def get_net_worth(self):
        return {
            "liquid_cents": self._liquid_cents,
            "investment_cents": 0,
            "debt_cents": 0,
            "net_worth_cents": self._liquid_cents,
        }


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

    async def get_price_changes(self, viewer_user_id=None):
        return list(self._price_changes)


class _FakeAccounts:
    def __init__(self, rows=None):
        self._rows = rows or []

    async def list_accounts(self, active_only: bool = True):
        return list(self._rows)


class _FakeBudgets:
    def __init__(self, rows=None):
        self._rows = rows or []

    async def get_progress(self, _month: str, viewer_user_id=None):
        return list(self._rows)


def _install_stub_repos(monkeypatch, *, reports=None, recurring=None, accounts=None, budgets=None):
    """Wire monkeypatched stubs for every repo the feed imports lazily."""
    monkeypatch.setattr(
        "web.reports.repo.ReportsRepository", lambda: reports or _FakeReports()
    )
    monkeypatch.setattr(
        "web.recurring.repo.RecurringRepository", lambda: recurring or _FakeRecurring()
    )
    monkeypatch.setattr(
        "web.accounts.repo.AccountsRepository", lambda: accounts or _FakeAccounts()
    )
    monkeypatch.setattr(
        "web.budgets.repo.BudgetsRepository", lambda: budgets or _FakeBudgets()
    )


@pytest.mark.asyncio
async def test_build_insights_feed_cards_and_actionable(monkeypatch):
    _install_stub_repos(monkeypatch)

    out = await build_insights_feed()

    types = {c["type"] for c in out["cards"]}
    assert "financial_health" in types
    assert "cash_flow_mom" in types
    assert "top_category" in types
    assert "forecast" in types
    assert isinstance(out["actionable_count"], int)
    assert "new_count" in out and isinstance(out["new_count"], int)
    # Every card must ship the Phase 2 envelope additions.
    for c in out["cards"]:
        assert "severity" in c and "title" in c
        assert "dedupe_key" in c and c["dedupe_key"], f"missing dedupe_key on {c['type']}"
        assert "action_url" in c and "action_label" in c, (
            f"missing action fields on {c['type']}"
        )
    # Phase 2 ships ``new_count == actionable_count``; Phase 4 decouples it.
    assert out["new_count"] == out["actionable_count"]


@pytest.mark.asyncio
async def test_build_insights_feed_propagates_viewer_user_id(monkeypatch):
    """Viewer id must be forwarded to ReportsRepository so privacy filter applies."""
    fake_reports = _FakeReports()
    _install_stub_repos(monkeypatch, reports=fake_reports)

    await build_insights_feed(viewer_user_id=42)

    # Every call should record viewer_user_id=42.
    assert fake_reports.last_viewer_user_id == 42


@pytest.mark.asyncio
async def test_liquidity_buffer_card_fires_when_forecast_exceeds_threshold(monkeypatch):
    """When 30-day forecast outflow eats > 40% of liquid cash, surface a warn card."""
    # _FakeRecurring's weekly $50 stream yields roughly 4 occurrences over 30
    # days (~$200 outflow). A $3 liquid balance makes the ratio obviously
    # exceed 40%, so the card must fire.
    reports = _FakeReports(liquid_cents=300)
    _install_stub_repos(monkeypatch, reports=reports)

    out = await build_insights_feed()

    types = {c["type"] for c in out["cards"]}
    assert "liquidity_buffer" in types
    card = next(c for c in out["cards"] if c["type"] == "liquidity_buffer")
    assert card["severity"] == "warn"
    assert card["action_url"] == "/recurring"
    assert card["dedupe_key"].startswith("liquidity_buffer:")


@pytest.mark.asyncio
async def test_liquidity_buffer_card_absent_with_ample_cash(monkeypatch):
    """Plenty of cash relative to forecast outflow → no heads-up card."""
    reports = _FakeReports(liquid_cents=10_000_000)  # $100k
    _install_stub_repos(monkeypatch, reports=reports)

    out = await build_insights_feed()

    types = {c["type"] for c in out["cards"]}
    assert "liquidity_buffer" not in types


@pytest.mark.asyncio
async def test_liquidity_buffer_card_absent_with_zero_liquid(monkeypatch):
    """If liquid is 0 we cannot meaningfully compute a ratio — stay silent."""
    reports = _FakeReports(liquid_cents=0)
    _install_stub_repos(monkeypatch, reports=reports)

    out = await build_insights_feed()

    types = {c["type"] for c in out["cards"]}
    assert "liquidity_buffer" not in types


@pytest.mark.asyncio
async def test_price_change_good_and_warn_cards(monkeypatch):
    """Signed price movements should surface as separate good/warn insight cards
    based on the stream direction."""
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
    _install_stub_repos(monkeypatch, recurring=_FakeRecurring(price_changes=streams))

    out = await build_insights_feed()
    types = {c["type"] for c in out["cards"]}
    assert "price_changes_good" in types
    assert "price_changes_warn" in types
    # actionable_count should have incremented from the warn card.
    assert out["actionable_count"] >= 1
