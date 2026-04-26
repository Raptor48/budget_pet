from datetime import date
from typing import List, Optional

from pydantic import BaseModel


class CashFlowMonth(BaseModel):
    """Monthly cash-flow summary.

    ``internal_transfer_cents`` is the absolute (outflow-side) total of
    moves between family accounts this month — surfaced for transparency
    so the UI can explain why the net differs from a naive income minus
    expense computation; it is never added into ``net_cents`` because
    transfers do not change family net worth.
    """

    month: str
    income_cents: int
    expenses_cents: int
    internal_transfer_cents: int = 0
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
    """One row in the Top-merchants list.

    ``merchant_name`` is the *display* name — when the household has set a
    ``merchant_alias`` for this merchant the alias is returned here and
    ``is_aliased`` is true so the UI can show a small "renamed" hint.
    Aggregation is done by aliased name (see ``ReportsRepository.get_top_merchants``).
    """

    merchant_name: str
    is_aliased: bool = False
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


class ExpenseSource(BaseModel):
    """A single category contributing to a user's monthly expenses.

    ``amount_cents`` is the signed sum (refunds reduce the bucket) so the
    UI can keep totals and category breakdown in sync. Refund-only
    categories whose net happens to be exactly zero are filtered out of
    the list in the repo to keep the chart clean.
    """

    category_id: Optional[int] = None
    category_name: str
    color: Optional[str] = None
    amount_cents: int
    transaction_count: int


class ExpenseByUser(BaseModel):
    user_id: Optional[int] = None
    username: str
    amount_cents: int
    sources: List[ExpenseSource]


class ExpenseBreakdown(BaseModel):
    """Mirror of ``IncomeBreakdown`` for expenses. Same grouping semantics
    so the Income and Expenses tabs share a single drill-down pattern."""

    month: str
    total_cents: int
    users: List[ExpenseByUser]


class ClassCounts(BaseModel):
    """Transaction-class histogram for a month."""

    income: int
    expense: int
    internal_transfer: int
    uncategorized: int
    total: int


class DiagnosticsRow(BaseModel):
    """Generic row returned by ``/api/reports/diagnostics``.

    The shape is intentionally permissive — this endpoint is for the owner
    to spot-check data and the exact field set per section can evolve.
    """

    id: int
    date: Optional[str] = None
    amount_cents: int
    merchant_name: Optional[str] = None
    name: Optional[str] = None
    pfc_primary: Optional[str] = None
    pfc_detailed: Optional[str] = None
    category_name: Optional[str] = None
    account_type: Optional[str] = None
    transaction_class: Optional[str] = None

    class Config:
        from_attributes = True


class Diagnostics(BaseModel):
    month: str
    counts: ClassCounts
    suspicious_income_category_with_positive_amount: List[DiagnosticsRow]
    transfer_pfc_not_classified_as_internal: List[DiagnosticsRow]
    large_uncategorized: List[DiagnosticsRow]


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
