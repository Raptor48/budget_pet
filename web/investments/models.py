from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class SecurityOut(BaseModel):
    plaid_security_id: str
    name: Optional[str] = None
    ticker_symbol: Optional[str] = None
    type: Optional[str] = None
    subtype: Optional[str] = None
    close_price: Optional[Decimal] = None
    close_price_as_of: Optional[date] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    currency: str = "USD"
    updated_at: datetime

    class Config:
        from_attributes = True


class HoldingOut(BaseModel):
    id: int
    account_id: int
    security_id: str
    quantity: Decimal
    institution_price: Optional[Decimal] = None
    institution_value_cents: Optional[int] = None
    cost_basis_cents: Optional[int] = None
    currency: str = "USD"
    last_synced_at: datetime
    security: Optional[SecurityOut] = None

    class Config:
        from_attributes = True
