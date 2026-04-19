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
    # Color/icon come from the bucket (parent when rolled up, self otherwise).
    color: Optional[str] = None
    # Stable id for the UI, e.g. "p:12" (primary parent) or "c:45" (child).
    bucket_key: Optional[str] = None
    # When the bucket rolls up children, which primary parent it represents
    # (None for already-top-level custom categories).
    parent_category_id: Optional[int] = None
    # In `rollup='primary'` mode, number of child categories sagged into this bucket.
    # In `rollup='detailed'` mode, this is 0.
    children_count: int = 0


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


class IncomeSource(BaseModel):
    category_id: Optional[int] = None
    category_name: str
    color: Optional[str] = None
    amount_cents: int
    transaction_count: int


class IncomeByUser(BaseModel):
    # ``user_id`` is None for income booked against accounts with no owner
    # (rare; the UI labels these "Unassigned").
    user_id: Optional[int] = None
    username: str
    amount_cents: int
    sources: List[IncomeSource]


class IncomeBreakdown(BaseModel):
    month: str
    total_cents: int
    users: List[IncomeByUser]


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
