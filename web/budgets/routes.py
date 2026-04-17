from datetime import date
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from .models import BudgetCreate, BudgetOut, BudgetProgressOut, BudgetUpdate
from .repo import BudgetsRepository

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


def _repo() -> BudgetsRepository:
    return BudgetsRepository()


@router.get("", response_model=List[BudgetOut])
async def list_budgets(month: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}$")):
    return await _repo().list_budgets(month=month)


@router.get("/progress", response_model=List[BudgetProgressOut])
async def get_progress(
    month: str = Query(default_factory=lambda: date.today().strftime("%Y-%m"), regex=r"^\d{4}-\d{2}$")
):
    return await _repo().get_progress(month)


@router.post("", response_model=BudgetOut, status_code=201)
async def create_budget(body: BudgetCreate):
    return await _repo().create_budget(body.model_dump())


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
