from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

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
    # Manual fallbacks — shown only when the corresponding Plaid field is
    # NULL. See ``web.accounts.missing_fields`` and ``docs/plaid.md``.
    credit_limit_cents_manual: Optional[int] = None
    apr_percent_manual: Optional[Decimal] = None
    # Which Plaid-sourced liability fields are currently missing on this
    # account. UI uses this list to surface "Not reported by bank" hints
    # and unlock the manual-override inputs.
    plaid_missing_fields: List[str] = Field(default_factory=list)
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
    institution_name: Optional[str] = None
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
    # Manual fallbacks for banks Plaid doesn't cover fully. The route
    # layer enforces that the matching Plaid value is NULL before
    # accepting a non-null override. Sending ``null`` clears the override
    # and is always allowed.
    credit_limit_cents_manual: Optional[int] = Field(None, ge=0)
    apr_percent_manual: Optional[Decimal] = Field(None, ge=0, le=Decimal("100"))
