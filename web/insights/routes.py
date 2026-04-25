from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from web.db import get_pool

from .store import (
    dismiss_card,
    get_feed_cached,
    invalidate_cache,
    snooze_card,
    unhide_card,
)

router = APIRouter(prefix="/api/insights", tags=["insights"])


class SnoozePayload(BaseModel):
    until: datetime = Field(..., description="ISO-8601 UTC time to snooze until")


@router.get("/feed")
async def insights_feed(
    request: Request,
    include_hidden: bool = Query(False),
):
    user = getattr(request.state, "user", None) or {}
    viewer_user_id = user.get("id")
    data = await get_feed_cached(
        viewer_user_id=int(viewer_user_id) if viewer_user_id is not None else None,
        include_hidden=include_hidden,
    )
    return {"generated_at": datetime.now(timezone.utc).isoformat(), **data}


@router.post("/mark-viewed")
async def mark_insights_viewed(request: Request):
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_preferences (user_id, insights_last_viewed_at, updated_at)
            VALUES ($1, NOW(), NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                insights_last_viewed_at = NOW(),
                updated_at = NOW()
            """,
            int(uid),
        )
    # ``new_count`` is computed against ``insights_last_viewed_at``, so bust
    # the cache for this viewer to force a fresh badge number on next fetch.
    invalidate_cache(int(uid))
    return {"ok": True}


def _require_uid(request: Request) -> int:
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return int(uid)


@router.post("/{dedupe_key:path}/dismiss")
async def dismiss_insight(dedupe_key: str, request: Request):
    uid = _require_uid(request)
    await dismiss_card(uid, dedupe_key)
    return {"ok": True}


@router.post("/{dedupe_key:path}/snooze")
async def snooze_insight(dedupe_key: str, request: Request, body: SnoozePayload):
    uid = _require_uid(request)
    until = body.until
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    try:
        applied = await snooze_card(uid, dedupe_key, until)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"ok": True, "snoozed_until": applied.isoformat()}


@router.post("/{dedupe_key:path}/unhide")
async def unhide_insight(dedupe_key: str, request: Request):
    uid = _require_uid(request)
    await unhide_card(uid, dedupe_key)
    return {"ok": True}
