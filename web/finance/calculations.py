"""
Interest calculations and analytics for finance module.
All calculations assume monthly compounding for simplicity.
"""

import calendar
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime
from typing import List, Optional, Tuple
from .models import (
    LoanOut, CreditCardOut, PaymentOut,
    AccountAnalytics, MonthlyInterest, PaymentAnalytics, InterestSummary
)


def calculate_monthly_interest_rate(apr_percent: Decimal) -> Decimal:
    """Convert APR to monthly interest rate."""
    if apr_percent <= 0:
        return Decimal('0')
    return apr_percent / Decimal('100') / Decimal('12')


def calculate_monthly_interest(balance_cents: int, apr_percent: Decimal, days_in_month: int = 30) -> int:
    """Calculate monthly interest in cents."""
    if balance_cents <= 0 or apr_percent <= 0:
        return 0
    
    monthly_rate = calculate_monthly_interest_rate(apr_percent)
    balance_dollars = Decimal(balance_cents) / Decimal('100')
    interest_dollars = balance_dollars * monthly_rate
    
    # Round to nearest cent
    interest_cents = int(interest_dollars.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) * 100)
    return interest_cents


def calculate_payoff_schedule(
    balance_cents: int,
    apr_percent: Decimal,
    payment_cents: int,
    max_months: int = 600  # 50 years max
) -> Tuple[int, int, int]:
    """
    Calculate payoff schedule for a debt.
    
    Returns:
        (months_to_payoff, total_interest_cents, total_cost_cents)
    """
    if balance_cents <= 0:
        return 0, 0, balance_cents
    
    if payment_cents <= 0:
        return max_months, 0, balance_cents  # Never pays off
    
    monthly_rate = calculate_monthly_interest_rate(apr_percent)
    
    if monthly_rate <= 0:
        # No interest, just divide balance by payment
        months = (balance_cents + payment_cents - 1) // payment_cents  # Ceiling division
        return min(months, max_months), 0, balance_cents
    
    current_balance = balance_cents
    total_interest = 0
    months = 0
    
    while current_balance > 0 and months < max_months:
        # Calculate interest for this month
        interest_cents = calculate_monthly_interest(current_balance, apr_percent)
        
        # Add interest to balance
        current_balance += interest_cents
        total_interest += interest_cents
        
        # Apply payment
        if payment_cents >= current_balance:
            # Final payment
            current_balance = 0
            months += 1
            break
        else:
            current_balance -= payment_cents
            months += 1
    
    total_cost = balance_cents + total_interest
    
    # If we hit max_months, return the values we have
    if months >= max_months:
        return max_months, total_interest, total_cost
    
    return months, total_interest, total_cost


def calculate_payment_analytics(
    payment: PaymentOut,
    balance_before_payment_cents: int,
    apr_percent: Decimal
) -> PaymentAnalytics:
    """Calculate analytics for a specific payment."""
    
    # Calculate interest portion (what would have accrued this month)
    interest_portion = calculate_monthly_interest(balance_before_payment_cents, apr_percent)
    
    # Principal portion is payment minus interest
    principal_portion = max(0, payment.amount_cents - interest_portion)
    
    # Remaining balance after payment
    remaining_balance = max(0, balance_before_payment_cents - payment.amount_cents)
    
    return PaymentAnalytics(
        payment_id=payment.id,
        amount_cents=payment.amount_cents,
        interest_portion_cents=interest_portion,
        principal_portion_cents=principal_portion,
        remaining_balance_cents=remaining_balance,
        months_saved=None  # Will be calculated separately if needed
    )


def calculate_account_analytics(
    account_id: int,
    account_type: str,
    name: str,
    current_balance_cents: int,
    apr_percent: Decimal,
    min_payment_cents: int,
    average_payment_cents: Optional[int] = None
) -> AccountAnalytics:
    """Calculate comprehensive analytics for an account."""
    
    monthly_rate = calculate_monthly_interest_rate(apr_percent)
    monthly_interest = calculate_monthly_interest(current_balance_cents, apr_percent)
    
    # Minimum payment projections
    min_months, min_interest, min_total_cost = calculate_payoff_schedule(
        current_balance_cents, apr_percent, min_payment_cents
    )
    
    # Current payment projections (use average or minimum)
    current_payment = average_payment_cents or min_payment_cents
    current_months, current_interest, current_total_cost = calculate_payoff_schedule(
        current_balance_cents, apr_percent, current_payment
    )
    
    # Calculate savings
    interest_savings = max(0, min_interest - current_interest)
    months_saved = max(0, min_months - current_months)
    
    return AccountAnalytics(
        account_id=account_id,
        account_type=account_type,
        name=name,
        current_balance_cents=current_balance_cents,
        apr_percent=apr_percent,
        monthly_interest_rate=monthly_rate,
        monthly_interest_cents=monthly_interest,
        min_payment_months=min_months if min_months < 600 else None,
        min_payment_total_interest_cents=min_interest,
        min_payment_total_cost_cents=min_total_cost,
        current_payoff_months=current_months if current_months < 600 else None,
        current_total_interest_cents=current_interest,
        current_total_cost_cents=current_total_cost,
        interest_savings_cents=interest_savings,
        months_saved=months_saved
    )


def calculate_average_payment(payments: List[PaymentOut], months_back: int = 6) -> Optional[int]:
    """Calculate average payment amount over the last N months."""
    if not payments:
        return None
    
    # Filter payments from last N months
    cutoff_date = date.today().replace(day=1)
    for _ in range(months_back):
        if cutoff_date.month == 1:
            cutoff_date = cutoff_date.replace(year=cutoff_date.year - 1, month=12)
        else:
            cutoff_date = cutoff_date.replace(month=cutoff_date.month - 1)
    
    recent_payments = [p for p in payments if p.occurred_at >= cutoff_date]
    
    if not recent_payments:
        return None
    
    total_amount = sum(p.amount_cents for p in recent_payments)
    return total_amount // len(recent_payments)


def generate_interest_summary(
    month: str,
    loans: List[LoanOut],
    cards: List[CreditCardOut],
    payments: List[PaymentOut]
) -> InterestSummary:
    """Generate comprehensive interest summary for a month."""
    
    # Calculate analytics for each account
    account_analytics = []
    total_interest_accrued = 0
    loans_interest = 0
    cards_interest = 0
    
    # Process loans
    for loan in loans:
        if not loan.is_active:
            continue
            
        # Get payments for this loan
        loan_payments = [p for p in payments if p.account_type == "loan" and p.account_id == loan.id]
        avg_payment = calculate_average_payment(loan_payments) or loan.min_payment_cents
        
        analytics = calculate_account_analytics(
            account_id=loan.id,
            account_type="loan",
            name=loan.name,
            current_balance_cents=loan.current_balance_cents,
            apr_percent=loan.apr_percent,
            min_payment_cents=loan.min_payment_cents,
            average_payment_cents=avg_payment
        )
        account_analytics.append(analytics)
        
        loans_interest += analytics.monthly_interest_cents
    
    # Process credit cards
    for card in cards:
        if not card.is_active:
            continue
            
        # Get payments for this card
        card_payments = [p for p in payments if p.account_type == "card" and p.account_id == card.id]
        avg_payment = calculate_average_payment(card_payments) or card.min_payment_cents
        
        analytics = calculate_account_analytics(
            account_id=card.id,
            account_type="card",
            name=card.name,
            current_balance_cents=card.current_balance_cents,
            apr_percent=card.apr_percent,
            min_payment_cents=card.min_payment_cents,
            average_payment_cents=avg_payment
        )
        account_analytics.append(analytics)
        
        cards_interest += analytics.monthly_interest_cents
    
    total_interest_accrued = loans_interest + cards_interest
    
    # Calculate overall projections
    total_min_interest = sum(a.min_payment_total_interest_cents for a in account_analytics)
    total_min_cost = sum(a.min_payment_total_cost_cents for a in account_analytics)
    max_min_months = max((a.min_payment_months or 0) for a in account_analytics) if account_analytics else 0
    
    total_current_interest = sum(a.current_total_interest_cents for a in account_analytics)
    total_current_cost = sum(a.current_total_cost_cents for a in account_analytics)
    max_current_months = max((a.current_payoff_months or 0) for a in account_analytics) if account_analytics else 0
    
    total_interest_savings = sum(a.interest_savings_cents for a in account_analytics)
    total_months_saved = max_min_months - max_current_months
    
    return InterestSummary(
        month=month,
        total_interest_accrued_cents=total_interest_accrued,
        loans_interest_cents=loans_interest,
        cards_interest_cents=cards_interest,
        total_projected_interest_cents=total_min_interest,
        total_projected_cost_cents=total_min_cost,
        projected_payoff_months=max_min_months,
        current_projected_interest_cents=total_current_interest,
        current_projected_cost_cents=total_current_cost,
        current_payoff_months=max_current_months,
        total_interest_savings_cents=total_interest_savings,
        total_months_saved=max(0, total_months_saved),
        account_analytics=account_analytics
    )
