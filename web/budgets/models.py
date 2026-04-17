from datetime import datetime
from typing import Optional

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


class BudgetCreate(BaseModel):
    category_id: int
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    budget_cents: int = Field(..., gt=0)


class BudgetUpdate(BaseModel):
    budget_cents: Optional[int] = Field(None, gt=0)
