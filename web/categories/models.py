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
    source: Literal["plaid_pfc", "custom"] = "custom"
    created_at: datetime

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
