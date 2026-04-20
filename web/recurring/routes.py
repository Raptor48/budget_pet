from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from .models import RecurringStreamCreate, RecurringStreamOut, RecurringStreamUpdate
from .repo import RecurringRepository

router = APIRouter(prefix="/api/recurring", tags=["recurring"])


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
):
    # Family-wide: every logged-in member (and admin) sees all household streams.
    # Per-account privacy is enforced elsewhere (e.g. Insights still passes viewer_user_id).
    return await _repo().list_streams(
        direction=direction,
        active_only=active_only,
        viewer_user_id=None,
    )


@router.get("/price-changes", response_model=List[RecurringStreamOut])
async def get_price_changes(_request: Request):
    """Return recurring streams where last price differs from average by more than 10%."""
    return await _repo().get_price_changes(viewer_user_id=None)


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
