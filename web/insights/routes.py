from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from web.db import get_pool

from .feed import build_insights_feed

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/feed")
async def insights_feed():
    data = await build_insights_feed()
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
    return {"ok": True}
