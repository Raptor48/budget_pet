"""Unit tests for the Phase-3 insight card builders in web/insights/cards.py."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from web.insights import cards as card_builders


# ---------------------------------------------------------------------------
# budget_risk
# ---------------------------------------------------------------------------


class TestBudgetRisk:
    def test_over_budget_emits_warn(self):
        rows = [
            {"id": 10, "category_name": "Dining", "budget_cents": 20000, "actual_cents": 25000},
        ]
        out = card_builders.build_budget_risk(rows, month="2026-04", today=date(2026, 4, 15))
        assert len(out) == 1
        c = out[0]
        assert c["type"] == "budget_risk"
        assert c["severity"] == "warn"
        assert "exceeded" in c["title"].lower() or "over" in c["summary"].lower()
        assert c["dedupe_key"] == "budget_risk:10:2026-04"
        assert c["action_url"] == "/budgets?month=2026-04"

    def test_early_month_at_risk(self):
        """At 90% with <20% of month elapsed → warn."""
        rows = [
            {"id": 11, "category_name": "Groceries", "budget_cents": 30000, "actual_cents": 27000},
        ]
        out = card_builders.build_budget_risk(
            rows, month="2026-04", today=date(2026, 4, 5)
        )
        assert len(out) == 1
        assert out[0]["severity"] == "warn"

    def test_late_month_at_risk_suppressed(self):
        """At 90% on day 28/30 is normal; no card."""
        rows = [
            {"id": 12, "category_name": "Fuel", "budget_cents": 10000, "actual_cents": 9000},
        ]
        out = card_builders.build_budget_risk(
            rows, month="2026-04", today=date(2026, 4, 28)
        )
        assert out == []

    def test_zero_budget_ignored(self):
        rows = [{"id": 1, "category_name": "x", "budget_cents": 0, "actual_cents": 500}]
        assert card_builders.build_budget_risk(rows, month="2026-04", today=date(2026, 4, 15)) == []


# ---------------------------------------------------------------------------
# category_trend
# ---------------------------------------------------------------------------


class TestCategoryTrend:
    def test_spike_emits_card(self):
        rows = [
            {
                "category_id": 7,
                "category_name": "Dining",
                "current_cents": 34_000,
                "avg_cents": 26_600,
                "prior_months": 3,
            }
        ]
        out = card_builders.build_category_trend(rows, month="2026-04")
        assert len(out) == 1
        c = out[0]
        assert c["type"] == "category_trend"
        assert c["severity"] == "warn"
        assert "Dining" in c["summary"]
        assert c["dedupe_key"] == "category_trend:7:2026-04"

    def test_decrease_does_not_emit(self):
        rows = [
            {
                "category_id": 7,
                "category_name": "Dining",
                "current_cents": 10_000,
                "avg_cents": 26_600,
                "prior_months": 3,
            }
        ]
        assert card_builders.build_category_trend(rows, month="2026-04") == []

    def test_no_history_skipped(self):
        rows = [
            {
                "category_id": 7,
                "category_name": "Dining",
                "current_cents": 40_000,
                "avg_cents": 0,
                "prior_months": 0,
            }
        ]
        assert card_builders.build_category_trend(rows, month="2026-04") == []

    def test_below_threshold_skipped(self):
        # +10% shouldn't trigger (threshold 25%)
        rows = [
            {
                "category_id": 8,
                "category_name": "Fuel",
                "current_cents": 11_000,
                "avg_cents": 10_000,
                "prior_months": 3,
            }
        ]
        assert card_builders.build_category_trend(rows, month="2026-04") == []


# ---------------------------------------------------------------------------
# missed_recurring
# ---------------------------------------------------------------------------


class TestMissedRecurring:
    def test_late_weekly_stream_emits_warn(self):
        today = date(2026, 4, 15)
        last = today - timedelta(days=15)  # well past weekly + grace
        streams = [
            {
                "id": 5,
                "is_active": True,
                "direction": "outflow",
                "last_date": last.isoformat(),
                "frequency": "WEEKLY",
                "last_amount_cents": 1500,
                "merchant_name": "Netflix",
                "description": "Netflix",
            }
        ]
        out = card_builders.build_missed_recurring(streams, today=today)
        assert len(out) == 1
        c = out[0]
        assert c["type"] == "missed_recurring"
        assert c["severity"] == "warn"
        assert "Netflix" in c["summary"]

    def test_within_grace_not_flagged(self):
        today = date(2026, 4, 15)
        last = today - timedelta(days=8)  # weekly period = 7, expected 2d ago, grace 3d
        streams = [
            {
                "id": 5,
                "is_active": True,
                "direction": "outflow",
                "last_date": last.isoformat(),
                "frequency": "WEEKLY",
                "last_amount_cents": 1500,
                "merchant_name": "Netflix",
            }
        ]
        # expected: today - 1, grace 3d → not late yet.
        assert card_builders.build_missed_recurring(streams, today=today) == []

    def test_tombstoned_skipped(self):
        today = date(2026, 4, 15)
        last = today - timedelta(days=60)
        streams = [
            {
                "id": 5,
                "is_active": True,
                "status": "TOMBSTONED",
                "direction": "outflow",
                "last_date": last.isoformat(),
                "frequency": "MONTHLY",
                "last_amount_cents": 1500,
                "merchant_name": "Netflix",
            }
        ]
        assert card_builders.build_missed_recurring(streams, today=today) == []

    def test_inflow_skipped(self):
        today = date(2026, 4, 15)
        last = today - timedelta(days=60)
        streams = [
            {
                "id": 5,
                "is_active": True,
                "direction": "inflow",
                "last_date": last.isoformat(),
                "frequency": "MONTHLY",
                "last_amount_cents": 300_000,
                "merchant_name": "Payroll",
            }
        ]
        assert card_builders.build_missed_recurring(streams, today=today) == []


# ---------------------------------------------------------------------------
# duplicate_subscription
# ---------------------------------------------------------------------------


class TestDuplicateSubscription:
    def test_detects_near_duplicate(self):
        streams = [
            {
                "id": 1,
                "is_active": True,
                "direction": "outflow",
                "last_amount_cents": 1500,
                "merchant_name": "Netflix",
            },
            {
                "id": 2,
                "is_active": True,
                "direction": "outflow",
                "last_amount_cents": 1599,  # within 20%
                "merchant_name": "Netflix",
            },
        ]
        out = card_builders.build_duplicate_subscription(streams)
        assert len(out) == 1
        c = out[0]
        assert c["type"] == "duplicate_subscription"
        assert c["severity"] == "warn"
        assert c["dedupe_key"] == "duplicate:1,2"

    def test_amounts_too_different_skipped(self):
        streams = [
            {"id": 1, "is_active": True, "direction": "outflow", "last_amount_cents": 1500, "merchant_name": "Netflix"},
            {"id": 2, "is_active": True, "direction": "outflow", "last_amount_cents": 5000, "merchant_name": "Netflix"},
        ]
        assert card_builders.build_duplicate_subscription(streams) == []

    def test_below_combined_floor_skipped(self):
        """Two $2 streams = $4 monthly, below the $5 combined floor."""
        streams = [
            {"id": 1, "is_active": True, "direction": "outflow", "last_amount_cents": 200, "merchant_name": "x"},
            {"id": 2, "is_active": True, "direction": "outflow", "last_amount_cents": 200, "merchant_name": "x"},
        ]
        assert card_builders.build_duplicate_subscription(streams) == []

    def test_tombstoned_excluded_from_group(self):
        streams = [
            {"id": 1, "is_active": True, "direction": "outflow", "last_amount_cents": 1500, "merchant_name": "Netflix"},
            {"id": 2, "is_active": True, "status": "TOMBSTONED", "direction": "outflow", "last_amount_cents": 1599, "merchant_name": "Netflix"},
        ]
        assert card_builders.build_duplicate_subscription(streams) == []


# ---------------------------------------------------------------------------
# overdue + utilization
# ---------------------------------------------------------------------------


class TestOverdueAndUtilization:
    def test_overdue_emits_warn(self):
        accounts = [
            {
                "id": 1,
                "name": "Chase Sapphire",
                "user_id": 10,
                "type": "credit",
                "is_active": True,
                "is_overdue": True,
                "min_payment_cents": 5000,
                "due_day": 15,
                "current_balance_cents": 1000,
                "credit_limit_cents": 10000,
            }
        ]
        out = card_builders.build_overdue_and_utilization(accounts, viewer_user_id=10)
        types = {c["type"] for c in out}
        assert "overdue_account" in types

    def test_high_utilization_warn(self):
        accounts = [
            {
                "id": 2,
                "name": "Amex",
                "user_id": 10,
                "type": "credit",
                "is_active": True,
                "is_overdue": False,
                "current_balance_cents": 8000,
                "credit_limit_cents": 10000,
            }
        ]
        out = card_builders.build_overdue_and_utilization(accounts, viewer_user_id=10)
        assert len(out) == 1
        c = out[0]
        assert c["type"] == "high_utilization"
        assert c["severity"] == "warn"
        assert "80%" in c["summary"]

    def test_moderate_utilization_info(self):
        accounts = [
            {
                "id": 3,
                "name": "Amex",
                "user_id": 10,
                "type": "credit",
                "is_active": True,
                "is_overdue": False,
                "current_balance_cents": 5000,
                "credit_limit_cents": 10000,  # 50%
            }
        ]
        out = card_builders.build_overdue_and_utilization(accounts, viewer_user_id=10)
        assert len(out) == 1
        assert out[0]["severity"] == "info"

    def test_low_utilization_no_card(self):
        accounts = [
            {
                "id": 4,
                "name": "Amex",
                "user_id": 10,
                "type": "credit",
                "is_active": True,
                "is_overdue": False,
                "current_balance_cents": 1000,
                "credit_limit_cents": 10000,  # 10%
            }
        ]
        assert card_builders.build_overdue_and_utilization(accounts, viewer_user_id=10) == []

    def test_other_user_account_skipped(self):
        """Non-shared account owned by another user is filtered out."""
        accounts = [
            {
                "id": 5,
                "name": "Partner card",
                "user_id": 999,
                "type": "credit",
                "is_active": True,
                "is_overdue": True,
                "current_balance_cents": 9000,
                "credit_limit_cents": 10000,
            }
        ]
        assert card_builders.build_overdue_and_utilization(accounts, viewer_user_id=10) == []

    def test_shared_account_visible(self):
        accounts = [
            {
                "id": 6,
                "name": "Shared card",
                "user_id": None,
                "type": "credit",
                "is_active": True,
                "is_overdue": True,
                "current_balance_cents": 9000,
                "credit_limit_cents": 10000,
            }
        ]
        out = card_builders.build_overdue_and_utilization(accounts, viewer_user_id=10)
        assert len(out) == 2  # overdue + high_utilization
