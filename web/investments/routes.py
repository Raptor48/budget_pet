from typing import List, Optional

from fastapi import APIRouter, Query

from .models import HoldingOut
from .repo import InvestmentsRepository

router = APIRouter(prefix="/api/investments", tags=["investments"])


def _repo() -> InvestmentsRepository:
    return InvestmentsRepository()


@router.get("/holdings", response_model=List[HoldingOut])
async def list_holdings(account_id: Optional[int] = Query(None)):
    return await _repo().list_holdings(account_id=account_id)
