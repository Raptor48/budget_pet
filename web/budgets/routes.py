from datetime import date
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from .models import (
    BudgetCopyResult,
    BudgetCreate,
    BudgetHistoryRow,
    BudgetOut,
    BudgetProgressOut,
    BudgetUpdate,
)
from .repo import BudgetsRepository

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


def _repo() -> BudgetsRepository:
    return BudgetsRepository()


@router.get("", response_model=List[BudgetOut])
async def list_budgets(month: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}$")):
    return await _repo().list_budgets(month=month)


@router.get("/progress", response_model=List[BudgetProgressOut])
async def get_progress(
    request: Request,
    month: str = Query(default_factory=lambda: date.today().strftime("%Y-%m"), regex=r"^\d{4}-\d{2}$"),
):
    user = getattr(request.state, "user", None) or {}
    viewer_user_id = user.get("id")
    return await _repo().get_progress(month, viewer_user_id=viewer_user_id)


@router.get("/history", response_model=List[BudgetHistoryRow])
async def get_history(
    request: Request,
    months: int = Query(12, ge=1, le=24),
):
    """Heatmap data for the Reports → Budget History tab.

    One row per category that had a budget in the last ``months`` months,
    each with a chronological timeline of (budget, actual, ratio). Cells
    without a budget come back with ``ratio = None`` so the UI can render
    them as neutral instead of green.
    """
    user = getattr(request.state, "user", None) or {}
    viewer_user_id = user.get("id")
    return await _repo().get_history(months=months, viewer_user_id=viewer_user_id)


@router.post("", response_model=BudgetOut, status_code=201)
async def create_budget(body: BudgetCreate):
    try:
        return await _repo().create_budget(body.model_dump())
    except ValueError as exc:
        # Hierarchy conflict (parent+child budgets in same month) or unknown id.
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/copy", response_model=BudgetCopyResult)
async def copy_budgets(
    from_month: str = Query(..., alias="from", regex=r"^\d{4}-\d{2}$"),
    to_month: str = Query(..., alias="to", regex=r"^\d{4}-\d{2}$"),
):
    """Bulk-copy every budget from ``from`` month into ``to`` month.

    Idempotent: rows that already exist in ``to`` for a given category are
    left as-is. Powers the "Copy from previous month" button on the
    Settings → Budgets page.
    """
    if from_month == to_month:
        raise HTTPException(status_code=400, detail="Source and destination months must differ")
    result = await _repo().copy_budgets(from_month=from_month, to_month=to_month)
    return result


@router.patch("/{budget_id}", response_model=BudgetOut)
async def update_budget(budget_id: int, body: BudgetUpdate):
    updated = await _repo().update_budget(budget_id, body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Budget not found")
    return updated


@router.delete("/{budget_id}", status_code=204)
async def delete_budget(budget_id: int):
    ok = await _repo().delete_budget(budget_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Budget not found")
