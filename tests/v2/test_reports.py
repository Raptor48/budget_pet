"""
Tests for web/reports/calculations.py — financial health score.
"""
import pytest

from web.reports.calculations import compute_health_score


class TestFinancialHealthScore:
    def test_healthy_finances_score_high(self):
        result = compute_health_score(
            total_debt_cents=50000,       # $500 debt
            annual_income_cents=600000,   # $6000/year
            monthly_income_cents=50000,   # $500/month
            monthly_expenses_cents=30000, # $300/month
            total_credit_limit_cents=100000,
            total_credit_balance_cents=10000,  # 10% utilization
            liquid_balance_cents=200000,  # $2000 liquid
            avg_monthly_expenses_cents=30000,
            has_overdue=False,
        )
        assert result["score"] >= 70
        assert result["label"] in ("Excellent", "Good")
        assert result["credit_utilization"] == pytest.approx(0.1, abs=0.01)
        assert result["savings_rate"] == pytest.approx(0.4, abs=0.01)

    def test_overdue_reduces_score(self):
        result_no_overdue = compute_health_score(
            total_debt_cents=0,
            annual_income_cents=600000,
            monthly_income_cents=50000,
            monthly_expenses_cents=30000,
            total_credit_limit_cents=100000,
            total_credit_balance_cents=5000,
            liquid_balance_cents=200000,
            avg_monthly_expenses_cents=30000,
            has_overdue=False,
        )
        result_with_overdue = compute_health_score(
            total_debt_cents=0,
            annual_income_cents=600000,
            monthly_income_cents=50000,
            monthly_expenses_cents=30000,
            total_credit_limit_cents=100000,
            total_credit_balance_cents=5000,
            liquid_balance_cents=200000,
            avg_monthly_expenses_cents=30000,
            has_overdue=True,
        )
        assert result_with_overdue["score"] < result_no_overdue["score"]
        assert "overdue" in result_with_overdue["advice"].lower()

    def test_high_utilization_reduces_score(self):
        result = compute_health_score(
            total_debt_cents=0,
            annual_income_cents=600000,
            monthly_income_cents=50000,
            monthly_expenses_cents=30000,
            total_credit_limit_cents=100000,
            total_credit_balance_cents=90000,  # 90% utilization
            liquid_balance_cents=200000,
            avg_monthly_expenses_cents=30000,
            has_overdue=False,
        )
        assert result["credit_utilization"] == pytest.approx(0.9, abs=0.01)
        assert result["score"] <= 80

    def test_spending_exceeds_income_reduces_score(self):
        result = compute_health_score(
            total_debt_cents=0,
            annual_income_cents=240000,
            monthly_income_cents=20000,
            monthly_expenses_cents=30000,  # spending > income
            total_credit_limit_cents=100000,
            total_credit_balance_cents=0,
            liquid_balance_cents=100000,
            avg_monthly_expenses_cents=30000,
            has_overdue=False,
        )
        assert result["savings_rate"] is not None
        assert result["savings_rate"] < 0
        assert "exceed" in result["advice"].lower() or "spending" in result["advice"].lower()

    def test_score_clamped_to_0_100(self):
        result = compute_health_score(
            total_debt_cents=10000000,
            annual_income_cents=10000,
            monthly_income_cents=833,
            monthly_expenses_cents=10000,
            total_credit_limit_cents=100000,
            total_credit_balance_cents=100000,
            liquid_balance_cents=0,
            avg_monthly_expenses_cents=10000,
            has_overdue=True,
        )
        assert 0 <= result["score"] <= 100
        assert result["color"]  # should have a color
