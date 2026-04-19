from datetime import date
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from .calculations import build_forecast, compute_health_score
from .models import (
    CashFlowMonth,
    CategorySpend,
    Diagnostics,
    ExpenseBreakdown,
    FinancialHealthScore,
    ForecastEntry,
    IncomeBreakdown,
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


@router.get("/income", response_model=IncomeBreakdown)
async def get_income_breakdown(
    request: Request,
    month: str = Query(
        default_factory=lambda: date.today().strftime("%Y-%m"),
        regex=r"^\d{4}-\d{2}$",
    ),
):
    """
    Per-person income for the month plus the per-category sources that make up
    each person's total. "Income" is defined by the family-wide ``is_income``
    flag on categories — see ``ReportsRepository.get_income_breakdown``.
    """
    return await _repo().get_income_breakdown(
        month, viewer_user_id=_viewer_id(request)
    )


@router.get("/financial-health", response_model=FinancialHealthScore)
async def get_financial_health(request: Request):
    data = await _repo().get_financial_health_data(viewer_user_id=_viewer_id(request))
    return compute_health_score(**data)


@router.get("/expenses", response_model=ExpenseBreakdown)
async def get_expense_breakdown(
    request: Request,
    month: str = Query(
        default_factory=lambda: date.today().strftime("%Y-%m"),
        regex=r"^\d{4}-\d{2}$",
    ),
):
    """Per-person expenses for the month, broken down by category.

    Mirror of ``GET /api/reports/income``. Expenses are defined by
    ``transaction_class = 'expense'`` (see ``docs/reports-math.md``) so
    internal transfers are excluded and refunds reduce the category they
    came from. Private transactions belonging to other family members are
    filtered out for the viewer.
    """
    return await _repo().get_expense_breakdown(
        month, viewer_user_id=_viewer_id(request)
    )


@router.get("/diagnostics", response_model=Diagnostics)
async def get_diagnostics(
    request: Request,
    month: str = Query(
        default_factory=lambda: date.today().strftime("%Y-%m"),
        regex=r"^\d{4}-\d{2}$",
    ),
):
    """
    Owner-only visibility into classifier edge cases for ``month``.

    Surfaces three buckets of suspect rows:
    - Income-flagged categories with a positive (debit) amount (likely
      miscategorised refunds or transfers).
    - Transfer-like PFCs (``TRANSFER_IN/OUT``, ``LOAN_PAYMENTS``) that the
      classifier could not confirm as internal transfers (no pair found,
      no name match) — candidates to add to
      ``app_settings.internal_transfer_names`` or to pair manually.
    - Uncategorized rows with non-trivial ``|amount_cents|`` — rows the
      classifier declined to bucket because their context (account type,
      pair, name) was ambiguous.
    """
    user = getattr(request.state, "user", None) or {}
    if not user.get("is_owner"):
        raise HTTPException(status_code=403, detail="Owner-only endpoint")
    return await _repo().get_diagnostics(month)
