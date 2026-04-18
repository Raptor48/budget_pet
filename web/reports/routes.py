from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Query, Request

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


def _viewer_id(request: Request) -> Optional[int]:
    user = getattr(request.state, "user", None) or {}
    return user.get("id")


@router.get("/cash-flow", response_model=CashFlowMonth)
async def get_cash_flow(
    request: Request,
    month: str = Query(default_factory=lambda: date.today().strftime("%Y-%m"), regex=r"^\d{4}-\d{2}$"),
):
    return await _repo().get_cash_flow(month, viewer_user_id=_viewer_id(request))


@router.get("/cash-flow/history", response_model=List[CashFlowMonth])
async def get_cash_flow_history(request: Request, months: int = Query(12, ge=1, le=24)):
    return await _repo().get_cash_flow_history(months, viewer_user_id=_viewer_id(request))


@router.get("/by-category", response_model=List[CategorySpend])
async def get_by_category(
    request: Request,
    month: str = Query(default_factory=lambda: date.today().strftime("%Y-%m"), regex=r"^\d{4}-\d{2}$"),
    rollup: str = Query(
        "primary",
        regex=r"^(primary|detailed)$",
        description="'primary' rolls detailed PFCs into their parent bucket (default). 'detailed' returns one row per detailed category.",
    ),
    parent_category_id: Optional[int] = Query(
        None,
        description="Only meaningful when rollup='detailed': scope results to children of this primary category.",
    ),
):
    return await _repo().get_by_category(
        month,
        viewer_user_id=_viewer_id(request),
        rollup=rollup,  # type: ignore[arg-type]
        parent_category_id=parent_category_id,
    )


@router.get("/by-tag", response_model=List[TagSpend])
async def get_by_tag(
    request: Request,
    month: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}$"),
    tag_id: Optional[int] = Query(None),
):
    return await _repo().get_by_tag(month=month, tag_id=tag_id, viewer_user_id=_viewer_id(request))


@router.get("/merchants", response_model=List[MerchantSpend])
async def get_top_merchants(
    request: Request,
    month: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}$"),
    limit: int = Query(10, ge=1, le=50),
):
    return await _repo().get_top_merchants(month=month, limit=limit, viewer_user_id=_viewer_id(request))


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
async def get_financial_health(request: Request):
    data = await _repo().get_financial_health_data(viewer_user_id=_viewer_id(request))
    return compute_health_score(**data)
