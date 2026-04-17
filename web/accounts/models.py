from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class AccountOut(BaseModel):
    id: int
    plaid_account_id: Optional[str] = None
    plaid_item_id: Optional[str] = None
    name: str
    official_name: Optional[str] = None
    mask: Optional[str] = None
    type: str
    subtype: Optional[str] = None
    current_balance_cents: int = 0
    available_balance_cents: Optional[int] = None
    credit_limit_cents: Optional[int] = None
    apr_percent: Optional[Decimal] = None
    min_payment_cents: Optional[int] = None
    due_day: Optional[int] = None
    is_overdue: Optional[bool] = None
    last_payment_date: Optional[date] = None
    last_statement_balance_cents: Optional[int] = None
    expected_payoff_date: Optional[date] = None
    ytd_interest_paid_cents: Optional[int] = None
    currency: str = "USD"
    holder_category: Optional[str] = None
    is_active: bool = True
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Institution branding (joined from plaid_items)
    institution_logo: Optional[str] = None
    institution_color: Optional[str] = None
    # Owner (joined from users via user_id)
    user_id: Optional[int] = None
    owner_username: Optional[str] = None
    is_cash_wallet: bool = False

    class Config:
        from_attributes = True


class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(..., pattern=r"^(depository|credit|loan|investment|other)$")
    subtype: Optional[str] = None
    official_name: Optional[str] = None
    mask: Optional[str] = None
    currency: str = "USD"
    holder_category: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    is_active: Optional[bool] = None
    holder_category: Optional[str] = None
    user_id: Optional[int] = None
    current_balance_cents: Optional[int] = None
