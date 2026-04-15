from pydantic import BaseModel
from typing import Optional, List, Dict

class ExpenseBase(BaseModel):
    category: str
    amount: float

class ExpenseCreate(ExpenseBase):
    date: Optional[str] = None  # YYYY-MM-DD format, defaults to today if not provided

class ExpenseUpdate(BaseModel):
    category: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[str] = None

class Expense(ExpenseBase):
    id: int
    date: str
    source: str = "manual"
    merchant_name: Optional[str] = None
    plaid_category_raw: Optional[str] = None
    plaid_pfc_category: Optional[str] = None
    is_pending: bool = False

    class Config:
        from_attributes = True

class ExpenseResponse(BaseModel):
    exceeded: bool
    remaining: float

class LimitBase(BaseModel):
    category: str
    default_limit: float

class LimitCreate(LimitBase):
    pass

class Limit(LimitBase):
    pass

class ReportItem(BaseModel):
    budget: float
    spent: float
    remaining: float

class ReportResponse(BaseModel):
    report: Dict[str, ReportItem]
    comparison: Optional[Dict[str, float]] = None

class SyncStatus(BaseModel):
    sha: Optional[str]
    last_sync: Optional[str]

class HealthResponse(BaseModel):
    ok: bool
