"""
Pydantic models for finance module with strict typing.
All money amounts stored as integer cents.
"""

from decimal import Decimal
from datetime import date, datetime
from typing import Optional, Literal, Dict, List
from pydantic import BaseModel, Field, conint, condecimal, validator


# Money conversion utilities
def money_to_cents(amount: float | str | Decimal) -> int:
    """Convert money amount to cents (integer)."""
    if isinstance(amount, str):
        amount = float(amount)
    return int(round(float(amount) * 100))


def cents_to_usd(cents: int) -> str:
    """Convert cents to USD string format (e.g., $1,234.56)."""
    dollars = cents / 100
    return f"${dollars:,.2f}"


def parse_month(month_str: str) -> tuple[date, date]:
    """Parse YYYY-MM string to (start_date, end_date) tuple."""
    year, month = map(int, month_str.split('-'))
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    return start_date, end_date


def now_tz() -> datetime:
    """Get current datetime in America/New_York timezone."""
    from datetime import timezone, timedelta
    # America/New_York is UTC-5 (EST) or UTC-4 (EDT)
    # For simplicity, using UTC-5 (EST)
    ny_tz = timezone(timedelta(hours=-5))
    return datetime.now(ny_tz)


# Base models
class LoanBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    category_name: str = Field(..., min_length=1, max_length=255)
    apr_percent: condecimal(ge=0, decimal_places=3) = Field(default=Decimal('0.000'))
    current_balance_cents: conint(ge=0) = Field(default=0)
    due_date: Optional[date] = None
    min_payment_cents: conint(ge=0) = Field(default=0)
    remaining_months: Optional[conint(ge=0)] = None
    close_date: Optional[date] = None
    is_active: bool = Field(default=True)


class LoanCreate(LoanBase):
    pass


class LoanUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    category_name: Optional[str] = Field(None, min_length=1, max_length=255)
    apr_percent: Optional[condecimal(ge=0, decimal_places=3)] = None
    current_balance_cents: Optional[conint(ge=0)] = None
    due_date: Optional[date] = None
    min_payment_cents: Optional[conint(ge=0)] = None
    remaining_months: Optional[conint(ge=0)] = None
    close_date: Optional[date] = None
    is_active: Optional[bool] = None


class LoanOut(LoanBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreditCardBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    category_name: str = Field(..., min_length=1, max_length=255)
    apr_percent: condecimal(ge=0, decimal_places=3) = Field(default=Decimal('0.000'))
    current_balance_cents: conint(ge=0) = Field(default=0)
    credit_limit_cents: Optional[conint(ge=0)] = None
    due_date: Optional[date] = None
    min_payment_cents: conint(ge=0) = Field(default=0)
    is_active: bool = Field(default=True)


class CreditCardCreate(CreditCardBase):
    pass


class CreditCardUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    category_name: Optional[str] = Field(None, min_length=1, max_length=255)
    apr_percent: Optional[condecimal(ge=0, decimal_places=3)] = None
    current_balance_cents: Optional[conint(ge=0)] = None
    credit_limit_cents: Optional[conint(ge=0)] = None
    due_date: Optional[date] = None
    min_payment_cents: Optional[conint(ge=0)] = None
    is_active: Optional[bool] = None


class CreditCardOut(CreditCardBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PaymentCreate(BaseModel):
    account_type: Literal["loan", "card"]
    account_id: conint(ge=1)
    amount_cents: conint(ge=1)
    occurred_at: Optional[date] = None  # Defaults to today if not provided
    person: Optional[Literal["Denis", "Taya"]] = None
    note: Optional[str] = Field(None, max_length=500)


class PaymentOut(BaseModel):
    id: int
    account_type: Literal["loan", "card"]
    account_id: int
    amount_cents: int
    occurred_at: date
    person: Optional[Literal["Denis", "Taya"]] = None
    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class IncomeBase(BaseModel):
    person: Literal["Denis", "Taya"]
    amount_cents: conint(ge=0)
    occurred_at: date
    note: Optional[str] = Field(None, max_length=500)


class IncomeCreate(IncomeBase):
    occurred_at: Optional[date] = None  # Defaults to today if not provided


class IncomeUpdate(BaseModel):
    person: Optional[Literal["Denis", "Taya"]] = None
    amount_cents: Optional[conint(ge=0)] = None
    occurred_at: Optional[date] = None
    note: Optional[str] = Field(None, max_length=500)


class IncomeOut(IncomeBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class LoanEstimatedClose(BaseModel):
    loan_id: int
    name: str
    remaining_months: int
    estimated_close_date: date


class DebtTotals(BaseModel):
    loans_balance_cents: int
    cards_balance_cents: int
    combined_balance_cents: int
    min_payments_cents: int


class SummaryOut(BaseModel):
    month: str
    income_total_cents: int
    income_by_person: Dict[Literal["Denis", "Taya"], int]
    debt_totals: DebtTotals
    loans_estimated_close: List[LoanEstimatedClose]


class AccountSummary(BaseModel):
    id: int
    name: str
    category_name: str


class AccountsOut(BaseModel):
    loans: List[AccountSummary]
    cards: List[AccountSummary]


# Interest and analytics models
class MonthlyInterest(BaseModel):
    """Monthly interest calculation for an account."""
    account_id: int
    account_type: Literal["loan", "card"]
    month: str  # YYYY-MM format
    interest_accrued_cents: int
    balance_start_cents: int
    balance_end_cents: int
    apr_percent: Decimal
    days_in_month: int


class PaymentAnalytics(BaseModel):
    """Analytics for a specific payment."""
    payment_id: int
    amount_cents: int
    interest_portion_cents: int
    principal_portion_cents: int
    remaining_balance_cents: int
    months_saved: Optional[int] = None  # Months saved by this payment vs minimum


class AccountAnalytics(BaseModel):
    """Analytics for a loan or credit card account."""
    account_id: int
    account_type: Literal["loan", "card"]
    name: str
    current_balance_cents: int
    apr_percent: Decimal
    
    # Interest calculations
    monthly_interest_rate: Decimal
    monthly_interest_cents: int
    
    # Payoff projections (minimum payments)
    min_payment_months: Optional[int] = None
    min_payment_total_interest_cents: int = 0
    min_payment_total_cost_cents: int = 0
    
    # Current payment projections (if paying more than minimum)
    current_payoff_months: Optional[int] = None
    current_total_interest_cents: int = 0
    current_total_cost_cents: int = 0
    
    # Savings from current payment strategy
    interest_savings_cents: int = 0
    months_saved: int = 0


class InterestSummary(BaseModel):
    """Overall interest and analytics summary."""
    month: str
    
    # Total interest accrued this month
    total_interest_accrued_cents: int
    loans_interest_cents: int
    cards_interest_cents: int
    
    # Projected totals (minimum payments)
    total_projected_interest_cents: int
    total_projected_cost_cents: int
    projected_payoff_months: int
    
    # Current strategy totals
    current_projected_interest_cents: int
    current_projected_cost_cents: int
    current_payoff_months: int
    
    # Savings from current strategy vs minimum
    total_interest_savings_cents: int
    total_months_saved: int
    
    # Account analytics
    account_analytics: List[AccountAnalytics]
