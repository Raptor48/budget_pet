from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class BudgetOut(BaseModel):
    id: int
    category_id: int
    month: str
    budget_cents: int
    created_at: datetime

    class Config:
        from_attributes = True


class BudgetProgressOut(BaseModel):
    category_id: int
    category_name: str
    category_color: str
    month: str
    budget_cents: int
    actual_cents: int
    remaining_cents: int
    percent_used: float
    # Signed delta of last month's budget vs actual for the same category:
    # positive = saved (under-spent), negative = over-spent. None when there
    # was no budget for the previous month. Surfaced as a "dopamine" badge
    # on each card — informational only, never folded into current totals.
    previous_month_diff_cents: Optional[int] = None


class BudgetCreate(BaseModel):
    category_id: int
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    budget_cents: int = Field(..., gt=0)


class BudgetUpdate(BaseModel):
    budget_cents: Optional[int] = Field(None, gt=0)


class BudgetCopyResult(BaseModel):
    """Result of POST /api/budgets/copy — what was copied and what was skipped."""

    from_month: str
    to_month: str
    copied: int
    skipped_existing: int


class BudgetHistoryMonth(BaseModel):
    """One cell of the Budget History heatmap: month × category outcome."""

    month: str
    budget_cents: int
    actual_cents: int
    # spent / budget — clamped to [0, ∞). 1.0 = exactly hit. >1.0 = over.
    # null when budget_cents is 0 (defensive; create endpoint disallows).
    ratio: Optional[float] = None


class BudgetHistoryRow(BaseModel):
    """One category's full timeline across the requested window."""

    category_id: int
    category_name: str
    category_color: str
    parent_id: Optional[int] = None
    months: List[BudgetHistoryMonth]
    # Convenience aggregates for the best/worst lists in the UI.
    months_with_budget: int
    months_under_or_at: int  # count of months where actual <= budget
