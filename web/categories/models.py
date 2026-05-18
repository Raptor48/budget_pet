from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CategoryOut(BaseModel):
    id: int
    name: str
    plaid_pfc_primary: Optional[str] = None
    plaid_pfc_detailed: Optional[str] = None
    color: str = "#3b82f6"
    icon: Optional[str] = None
    pfc_icon_url: Optional[str] = None
    source: Literal["plaid_pfc", "custom", "system"] = "custom"
    created_at: datetime
    # NULL = top-level (primary/custom root). Depth is always ≤ 2 in the DB.
    parent_id: Optional[int] = None
    # Family-wide flag: TRUE means transactions mapped to this category are
    # treated as income in every income aggregate (Income tab, Cash Flow,
    # Financial Health, ...). Defaults are seeded from Plaid PFC=INCOME and
    # can be toggled per family via PATCH /api/categories/{id}.
    is_income: bool = False
    # When TRUE the category behaves as a *ledger*, not a real income/expense
    # bucket: its splits are excluded from every income/expense aggregate,
    # and the SUM(amount_cents) tells you outstanding balance (positive =
    # owed to you, negative = you owe). Used by the built-in ``Shared``
    # category and any future receivable-style buckets.
    is_receivable: bool = False

    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    """User-defined category only; Plaid-linked rows are created during sync."""

    name: str = Field(..., min_length=1, max_length=100)
    color: str = "#3b82f6"
    icon: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    color: Optional[str] = None
    icon: Optional[str] = None
    is_income: Optional[bool] = None
