from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Query

from .calculations import build_forecast, compute_health_score
from .models import (
    CashFlowMonth,
    CategorySpend,
    FinancialHealthScore,
    ForecastEntry,
    MerchantSpend,
    NetWorthSnapshot,
    TagSpend,
)
from .repo import ReportsRepository
from web.recurring.repo import RecurringRepository

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _repo() -> ReportsRepository:
    return ReportsRepository()


@router.get("/cash-flow", response_model=CashFlowMonth)
async def get_cash_flow(
    month: str = Query(default_factory=lambda: date.today().strftime("%Y-%m"), regex=r"^\d{4}-\d{2}$")
):
    return await _repo().get_cash_flow(month)


@router.get("/cash-flow/history", response_model=List[CashFlowMonth])
async def get_cash_flow_history(months: int = Query(12, ge=1, le=24)):
    return await _repo().get_cash_flow_history(months)


@router.get("/by-category", response_model=List[CategorySpend])
async def get_by_category(
    month: str = Query(default_factory=lambda: date.today().strftime("%Y-%m"), regex=r"^\d{4}-\d{2}$")
):
    return await _repo().get_by_category(month)


@router.get("/by-tag", response_model=List[TagSpend])
async def get_by_tag(
    month: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}$"),
    tag_id: Optional[int] = Query(None),
):
    return await _repo().get_by_tag(month=month, tag_id=tag_id)


@router.get("/merchants", response_model=List[MerchantSpend])
async def get_top_merchants(
    month: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}$"),
    limit: int = Query(10, ge=1, le=50),
):
    return await _repo().get_top_merchants(month=month, limit=limit)


@router.get("/net-worth")
async def get_net_worth():
    return await _repo().get_net_worth()


@router.get("/net-worth/history", response_model=List[NetWorthSnapshot])
async def get_net_worth_history(months: int = Query(12, ge=1, le=60)):
    return await _repo().get_net_worth_history(months)


@router.get("/forecast", response_model=List[ForecastEntry])
async def get_forecast(days: int = Query(30, ge=1, le=90)):
    streams = await RecurringRepository().list_streams(direction="outflow", active_only=True)
    entries = build_forecast(streams, days=days)
    return entries


@router.get("/financial-health", response_model=FinancialHealthScore)
async def get_financial_health():
    data = await _repo().get_financial_health_data()
    return compute_health_score(**data)
