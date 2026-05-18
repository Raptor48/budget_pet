from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from .models import (
    RecurringBulkAction,
    RecurringBulkResult,
    RecurringStreamCreate,
    RecurringStreamOut,
    RecurringStreamUpdate,
)
from .repo import RecurringRepository

router = APIRouter(prefix="/api/recurring", tags=["recurring"])

VALID_USER_STATUSES = ("active", "paused", "cancelled", "unsubscribed")


def _repo() -> RecurringRepository:
    return RecurringRepository()


@router.post("", response_model=RecurringStreamOut, status_code=201)
async def create_stream(request: Request, body: RecurringStreamCreate):
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        row = await _repo().create_manual_stream(int(uid), body.model_dump())
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid account for this user") from None
    return row


@router.get("", response_model=List[RecurringStreamOut])
async def list_streams(
    _request: Request,
    direction: Optional[str] = Query(None, pattern=r"^(inflow|outflow)$"),
    active_only: bool = Query(True),
    user_status: Optional[List[str]] = Query(
        None,
        description=(
            "Repeatable filter on user_status. Values: "
            "active, paused, unsubscribed, cancelled. "
            "Default = active+paused+unsubscribed (cancelled is hidden)."
        ),
    ),
):
    # Family-wide: every logged-in member (and admin) sees all household streams.
    # Per-account privacy is enforced elsewhere (e.g. Insights still passes viewer_user_id).
    if user_status:
        invalid = [s for s in user_status if s not in VALID_USER_STATUSES]
        if invalid:
            raise HTTPException(
                status_code=422, detail=f"Invalid user_status value: {invalid[0]}"
            )
    return await _repo().list_streams(
        direction=direction,
        active_only=active_only,
        viewer_user_id=None,
        include_user_statuses=user_status,
    )


@router.get("/price-changes", response_model=List[RecurringStreamOut])
async def get_price_changes(_request: Request):
    """Return recurring streams where last price differs from average by more than 10%."""
    return await _repo().get_price_changes(viewer_user_id=None)


@router.post("/bulk", response_model=RecurringBulkResult)
async def bulk_apply(body: RecurringBulkAction):
    """Apply one lifecycle action to a list of stream ids:

    * ``cancel`` — terminal: stream disappears from the recurring list.
    * ``pause`` — temporary mute, optional ``paused_until``.
    * ``reactivate`` — back to ``active``.
    * ``unsubscribe`` — pending verification. The user declared they
      cancelled at the merchant; the nightly verifier confirms after one
      cadence + grace, either moving the stream to ``cancelled`` (no
      charge posted → confirmed) or firing a P0 alert (charge posted →
      cancellation may not have gone through).
    * ``snooze_price_change`` — hide the price-change badge for N days.

    Plaid does not let third-party subscriptions be paused or cancelled
    via API — this endpoint only flips local state for KPI / Insights
    filtering. The user is still expected to cancel with the merchant
    directly.
    """
    updated = await _repo().bulk_apply(
        ids=body.ids,
        action=body.action,
        paused_until=body.paused_until,
        snooze_days=body.snooze_days,
    )
    return RecurringBulkResult(updated=updated)


@router.get("/{stream_id}", response_model=RecurringStreamOut)
async def get_stream(stream_id: int):
    stream = await _repo().get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")
    return stream


@router.patch("/{stream_id}", response_model=RecurringStreamOut)
async def update_stream(stream_id: int, body: RecurringStreamUpdate):
    updated = await _repo().update_stream(stream_id, body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Stream not found")
    return updated
