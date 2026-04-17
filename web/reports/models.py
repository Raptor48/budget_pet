from datetime import date
from typing import List, Optional

from pydantic import BaseModel


class CashFlowMonth(BaseModel):
    month: str
    income_cents: int
    expenses_cents: int
    net_cents: int


class CategorySpend(BaseModel):
    category_id: Optional[int] = None
    category_name: str
    amount_cents: int
    percent: float


class TagSpend(BaseModel):
    tag_id: int
    tag_name: str
    tag_color: str
    amount_cents: int


class MerchantSpend(BaseModel):
    merchant_name: str
    logo_url: Optional[str] = None
    amount_cents: int
    transaction_count: int


class NetWorthSnapshot(BaseModel):
    snapshot_date: date
    liquid_cents: int
    investment_cents: int
    debt_cents: int
    net_worth_cents: int


class ForecastEntry(BaseModel):
    date: date
    description: str
    merchant_name: Optional[str] = None
    amount_cents: int
    frequency: Optional[str] = None
    stream_id: int


class FinancialHealthScore(BaseModel):
    score: int
    label: str
    color: str
    debt_to_income: Optional[float] = None
    credit_utilization: Optional[float] = None
    savings_rate: Optional[float] = None
    emergency_fund_months: Optional[float] = None
    has_overdue: bool = False
    advice: str
