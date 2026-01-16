"""
Tests for financial calculations (interest, payoff schedules, analytics).
"""
import pytest
from decimal import Decimal
from datetime import date, datetime
from web.finance.calculations import (
    calculate_monthly_interest_rate,
    calculate_monthly_interest,
    calculate_payoff_schedule,
    calculate_account_analytics,
    calculate_average_payment,
    generate_interest_summary
)
from web.finance.models import (
    LoanOut, CreditCardOut, PaymentOut, InterestSummary
)


class TestMonthlyInterestRate:
    """Tests for monthly interest rate calculation."""
    
    def test_zero_apr(self):
        """Test that zero APR returns zero rate."""
        assert calculate_monthly_interest_rate(Decimal("0")) == Decimal("0")
    
    def test_positive_apr(self):
        """Test positive APR conversion."""
        # 12% APR = 1% monthly
        result = calculate_monthly_interest_rate(Decimal("12"))
        expected = Decimal("12") / Decimal("100") / Decimal("12")
        assert result == expected
        assert float(result) == pytest.approx(0.01, rel=1e-6)
    
    def test_high_apr(self):
        """Test high APR (credit card)."""
        # 24.99% APR
        result = calculate_monthly_interest_rate(Decimal("24.99"))
        expected = Decimal("24.99") / Decimal("100") / Decimal("12")
        assert float(result) == pytest.approx(0.020825, rel=1e-4)


class TestMonthlyInterest:
    """Tests for monthly interest calculation."""
    
    def test_zero_balance(self):
        """Test that zero balance returns zero interest."""
        assert calculate_monthly_interest(0, Decimal("5.5")) == 0
    
    def test_zero_apr(self):
        """Test that zero APR returns zero interest."""
        assert calculate_monthly_interest(100000, Decimal("0")) == 0
    
    def test_standard_loan(self):
        """Test interest calculation for standard loan."""
        # $25,000 at 5.5% APR
        balance_cents = 2500000
        apr = Decimal("5.5")
        
        interest = calculate_monthly_interest(balance_cents, apr)
        
        # Monthly rate = 5.5% / 12 = 0.4583%
        # Interest = $25,000 * 0.004583 = $114.58
        expected_cents = 11458  # $114.58
        assert interest == pytest.approx(expected_cents, abs=1)
    
    def test_credit_card_interest(self):
        """Test interest calculation for credit card."""
        # $1,500 at 24.99% APR
        balance_cents = 150000
        apr = Decimal("24.99")
        
        interest = calculate_monthly_interest(balance_cents, apr)
        
        # Monthly rate = 24.99% / 12 = 2.0825%
        # Interest = $1,500 * 0.020825 = $31.24
        expected_cents = 3124  # $31.24
        assert interest == pytest.approx(expected_cents, abs=1)
    
    def test_rounding(self):
        """Test that interest is rounded to nearest cent."""
        # $100 at 5% APR
        balance_cents = 10000
        apr = Decimal("5")
        
        interest = calculate_monthly_interest(balance_cents, apr)
        
        # Should be exactly $0.42 (rounded)
        assert interest == 42


class TestPayoffSchedule:
    """Tests for payoff schedule calculation."""
    
    def test_zero_balance(self):
        """Test that zero balance pays off immediately."""
        months, interest, cost = calculate_payoff_schedule(0, Decimal("5.5"), 50000)
        assert months == 0
        assert interest == 0
        assert cost == 0
    
    def test_zero_payment(self):
        """Test that zero payment never pays off."""
        months, interest, cost = calculate_payoff_schedule(2500000, Decimal("5.5"), 0)
        assert months == 600  # Max months
        # With zero payment, balance grows with interest, so cost should be higher
        # But the function returns original balance if payment is 0
        assert cost >= 2500000  # Balance doesn't decrease
    
    def test_zero_apr_payoff(self):
        """Test payoff with zero interest."""
        # $10,000 at 0% APR, $500/month payment
        months, interest, cost = calculate_payoff_schedule(1000000, Decimal("0"), 50000)
        assert months == 20  # 10,000 / 500 = 20 months
        assert interest == 0
        assert cost == 1000000
    
    def test_standard_loan_payoff(self):
        """Test payoff schedule for standard loan."""
        # $25,000 at 5.5% APR, $500/month payment
        balance_cents = 2500000
        apr = Decimal("5.5")
        payment_cents = 50000
        
        months, interest, cost = calculate_payoff_schedule(balance_cents, apr, payment_cents)
        
        # Should pay off in approximately 50-60 months (adjusted for actual calculation)
        assert 50 <= months <= 60
        assert interest > 0  # Should accrue interest
        assert cost > balance_cents  # Total cost > principal
        assert cost == balance_cents + interest
    
    def test_large_payment_payoff(self):
        """Test payoff with large payment (pays off quickly)."""
        # $25,000 at 5.5% APR, $1,000/month payment
        balance_cents = 2500000
        apr = Decimal("5.5")
        payment_cents = 100000
        
        months, interest, cost = calculate_payoff_schedule(balance_cents, apr, payment_cents)
        
        # Should pay off in approximately 26-28 months
        assert 26 <= months <= 28
        assert interest > 0
        assert cost < balance_cents * 1.1  # Less than 10% interest
    
    def test_minimum_payment_trap(self):
        """Test that minimum payment barely covers interest."""
        # $1,500 at 24.99% APR, $25/month payment (minimum)
        balance_cents = 150000
        apr = Decimal("24.99")
        payment_cents = 2500  # $25
        
        months, interest, cost = calculate_payoff_schedule(balance_cents, apr, payment_cents)
        
        # Should take very long to pay off (if at all)
        assert months >= 100  # Takes many years
        assert interest > balance_cents  # Interest > principal


class TestAccountAnalytics:
    """Tests for account analytics calculation."""
    
    def test_loan_analytics(self):
        """Test analytics for a loan."""
        analytics = calculate_account_analytics(
            account_id=1,
            account_type="loan",
            name="Test Loan",
            current_balance_cents=2500000,  # $25,000
            apr_percent=Decimal("5.5"),
            min_payment_cents=50000,  # $500
            average_payment_cents=100000  # $1,000
        )
        
        assert analytics.account_id == 1
        assert analytics.account_type == "loan"
        assert analytics.current_balance_cents == 2500000
        assert analytics.apr_percent == Decimal("5.5")
        assert analytics.monthly_interest_cents > 0
        assert analytics.min_payment_months is not None
        assert analytics.current_payoff_months is not None
        assert analytics.current_payoff_months < analytics.min_payment_months
        assert analytics.interest_savings_cents > 0
        assert analytics.months_saved > 0
    
    def test_card_analytics(self):
        """Test analytics for a credit card."""
        analytics = calculate_account_analytics(
            account_id=1,
            account_type="card",
            name="Test Card",
            current_balance_cents=150000,  # $1,500
            apr_percent=Decimal("24.99"),
            min_payment_cents=2500,  # $25
            average_payment_cents=5000  # $50
        )
        
        assert analytics.account_type == "card"
        assert analytics.monthly_interest_cents > 0
        assert analytics.min_payment_total_interest_cents > 0
        assert analytics.current_total_interest_cents < analytics.min_payment_total_interest_cents


class TestAveragePayment:
    """Tests for average payment calculation."""
    
    def test_empty_payments(self):
        """Test with no payments."""
        result = calculate_average_payment([])
        assert result is None
    
    def test_single_payment(self):
        """Test with single payment."""
        payments = [
            PaymentOut(
                id=1,
                account_type="loan",
                account_id=1,
                amount_cents=50000,
                occurred_at=date(2025, 1, 15),
                person="Denis",
                note="Test",
                created_at=datetime(2025, 1, 15, 12, 0, 0)
            )
        ]
        # Use reference_date to ensure payment is within range
        result = calculate_average_payment(payments, months_back=6, reference_date=date(2025, 1, 1))
        assert result == 50000
    
    def test_multiple_payments(self):
        """Test with multiple payments."""
        payments = [
            PaymentOut(
                id=1,
                account_type="loan",
                account_id=1,
                amount_cents=50000,
                occurred_at=date(2025, 1, 15),
                person="Denis",
                note="Test",
                created_at=datetime(2025, 1, 15, 12, 0, 0)
            ),
            PaymentOut(
                id=2,
                account_type="loan",
                account_id=1,
                amount_cents=75000,
                occurred_at=date(2025, 2, 15),
                person="Denis",
                note="Test",
                created_at=datetime(2025, 2, 15, 12, 0, 0)
            ),
            PaymentOut(
                id=3,
                account_type="loan",
                account_id=1,
                amount_cents=100000,
                occurred_at=date(2025, 3, 15),
                person="Denis",
                note="Test",
                created_at=datetime(2025, 3, 15, 12, 0, 0)
            )
        ]
        # Use reference_date to ensure all payments are within range
        result = calculate_average_payment(payments, months_back=6, reference_date=date(2025, 3, 1))
        # Average of 50, 75, 100 = 75
        assert result == 75000
    
    def test_filter_by_date(self):
        """Test filtering payments by date."""
        payments = [
            PaymentOut(
                id=1,
                account_type="loan",
                account_id=1,
                amount_cents=50000,
                occurred_at=date(2024, 6, 15),  # Old payment (more than 6 months ago from 2025-01)
                person="Denis",
                note="Test",
                created_at=datetime(2024, 6, 15, 12, 0, 0)
            ),
            PaymentOut(
                id=2,
                account_type="loan",
                account_id=1,
                amount_cents=100000,
                occurred_at=date(2025, 1, 15),  # Recent payment (within 6 months)
                person="Denis",
                note="Test",
                created_at=datetime(2025, 1, 15, 12, 0, 0)
            )
        ]
        # Should only count recent payment (last 6 months from 2025-01-01)
        # Reference date is 2025-01-01, so cutoff is 2024-07-01
        # Payment from 2024-06-15 should be excluded (< 2024-07-01), only 2025-01-15 should count
        result = calculate_average_payment(payments, months_back=6, reference_date=date(2025, 1, 1))
        assert result == 100000


class TestInterestSummary:
    """Tests for interest summary generation."""
    
    def test_empty_summary(self):
        """Test summary with no accounts."""
        summary = generate_interest_summary(
            month="2025-01",
            loans=[],
            cards=[],
            payments=[]
        )
        
        assert summary.month == "2025-01"
        assert summary.total_interest_accrued_cents == 0
        assert summary.loans_interest_cents == 0
        assert summary.cards_interest_cents == 0
        assert len(summary.account_analytics) == 0
    
    def test_summary_with_loans(self):
        """Test summary with loans."""
        loans = [
            LoanOut(
                id=1,
                name="Loan 1",
                category_name="Auto",
                apr_percent=Decimal("5.5"),
                current_balance_cents=2500000,
                due_day=15,
                min_payment_cents=50000,
                remaining_months=36,
                close_date=None,
                is_active=True,
                created_at="2025-01-01T00:00:00Z",
                updated_at="2025-01-01T00:00:00Z"
            )
        ]
        
        summary = generate_interest_summary(
            month="2025-01",
            loans=loans,
            cards=[],
            payments=[]
        )
        
        assert summary.total_interest_accrued_cents > 0
        assert summary.loans_interest_cents > 0
        assert summary.cards_interest_cents == 0
        assert len(summary.account_analytics) == 1
    
    def test_summary_with_cards(self):
        """Test summary with credit cards."""
        cards = [
            CreditCardOut(
                id=1,
                name="Card 1",
                category_name="Chase",
                apr_percent=Decimal("24.99"),
                current_balance_cents=150000,
                credit_limit_cents=500000,
                due_day=20,
                min_payment_cents=2500,
                is_active=True,
                created_at="2025-01-01T00:00:00Z",
                updated_at="2025-01-01T00:00:00Z"
            )
        ]
        
        summary = generate_interest_summary(
            month="2025-01",
            loans=[],
            cards=cards,
            payments=[]
        )
        
        assert summary.total_interest_accrued_cents > 0
        assert summary.loans_interest_cents == 0
        assert summary.cards_interest_cents > 0
        assert len(summary.account_analytics) == 1
    
    def test_summary_with_payments(self):
        """Test summary with payments (affects average payment)."""
        loans = [
            LoanOut(
                id=1,
                name="Loan 1",
                category_name="Auto",
                apr_percent=Decimal("5.5"),
                current_balance_cents=2500000,
                due_day=15,
                min_payment_cents=50000,
                remaining_months=36,
                close_date=None,
                is_active=True,
                created_at="2025-01-01T00:00:00Z",
                updated_at="2025-01-01T00:00:00Z"
            )
        ]
        
        payments = [
            PaymentOut(
                id=1,
                account_type="loan",
                account_id=1,
                amount_cents=100000,  # $1,000 (higher than minimum)
                occurred_at=date(2025, 1, 15),
                person="Denis",
                note="Extra payment",
                created_at=datetime(2025, 1, 15, 12, 0, 0)
            )
        ]
        
        summary = generate_interest_summary(
            month="2025-01",
            loans=loans,
            cards=[],
            payments=payments
        )
        
        assert len(summary.account_analytics) == 1
        analytics = summary.account_analytics[0]
        # With higher payments, should save interest
        assert analytics.interest_savings_cents > 0
        assert analytics.months_saved > 0
