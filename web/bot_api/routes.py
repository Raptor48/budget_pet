"""
REST API for the frontend ``Bot`` section under /api/bot/*.

Mirrors every read/write the Telegram bot does in-process so the user can
manage everything from the web app too — chores, audit history, anniversary,
milestones, mood log, notification preferences, and receipts. The Telegram
bot itself bypasses HTTP and calls the same repository directly.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response

from web.transactions.repo import TransactionsRepository

from .models import (
    AuditSessionOut,
    AuditSessionUpdate,
    ChoreAssignmentOut,
    ChoreCompletionUpdate,
    ChoreCreate,
    ChoreOut,
    ChoreUpdate,
    CoupleSettingsOut,
    CoupleSettingsUpdate,
    LeaderboardOut,
    MilestoneCreate,
    MilestoneOut,
    MoodEntryOut,
    MoodEntryUpsert,
    NotificationPrefOut,
    NotificationPrefUpdate,
    ReceiptOut,
    StreakOut,
    TelegramLinkCodeOut,
    TelegramLinkStatus,
)
from .repo import _week_start, get_bot_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot", tags=["bot"])


def _user_id(request: Request) -> int:
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return int(uid)


# ---------------------------------------------------------------------------
# Telegram link
# ---------------------------------------------------------------------------

@router.get("/telegram/status", response_model=TelegramLinkStatus)
async def telegram_status(request: Request):
    return await get_bot_repo().get_telegram_link_status(_user_id(request))


@router.post("/telegram/link", response_model=TelegramLinkCodeOut)
async def telegram_link_code(request: Request):
    """Issue a fresh link code. The user pastes it into the bot via /link <code>."""
    code = await get_bot_repo().issue_telegram_link_code(_user_id(request))
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME") or None
    return {**code, "bot_username": bot_username}


@router.delete("/telegram/link", status_code=204)
async def telegram_unlink(request: Request):
    await get_bot_repo().detach_telegram_chat(_user_id(request))


# ---------------------------------------------------------------------------
# Couple / bot settings (anniversary, mood threshold, brief time, quiet hours)
# ---------------------------------------------------------------------------

@router.get("/settings", response_model=CoupleSettingsOut)
async def get_settings(request: Request):
    return await get_bot_repo().get_couple_settings(_user_id(request))


@router.put("/settings", response_model=CoupleSettingsOut)
async def update_settings(request: Request, body: CoupleSettingsUpdate):
    patch = body.model_dump(exclude_unset=True)
    return await get_bot_repo().update_couple_settings(_user_id(request), patch)


# ---------------------------------------------------------------------------
# Notification prefs
# ---------------------------------------------------------------------------

@router.get("/notifications", response_model=List[NotificationPrefOut])
async def list_notification_prefs(request: Request):
    return await get_bot_repo().list_notification_prefs(_user_id(request))


@router.put("/notifications/{alert_type}", response_model=NotificationPrefOut)
async def set_notification_pref(
    request: Request, alert_type: str, body: NotificationPrefUpdate
):
    return await get_bot_repo().set_notification_pref(
        _user_id(request), alert_type, body.enabled
    )


# ---------------------------------------------------------------------------
# Chores
# ---------------------------------------------------------------------------

@router.get("/chores", response_model=List[ChoreOut])
async def list_chores(request: Request):
    _user_id(request)
    return await get_bot_repo().list_chores()


@router.post("/chores", response_model=ChoreOut, status_code=201)
async def create_chore(request: Request, body: ChoreCreate):
    _user_id(request)
    return await get_bot_repo().create_chore(body.model_dump())


@router.patch("/chores/{chore_id}", response_model=ChoreOut)
async def update_chore(request: Request, chore_id: int, body: ChoreUpdate):
    _user_id(request)
    patch = body.model_dump(exclude_unset=True)
    row = await get_bot_repo().update_chore(chore_id, patch)
    if not row:
        raise HTTPException(status_code=404, detail="Chore not found")
    return row


@router.delete("/chores/{chore_id}", status_code=204)
async def delete_chore(request: Request, chore_id: int):
    _user_id(request)
    if not await get_bot_repo().delete_chore(chore_id):
        raise HTTPException(status_code=404, detail="Chore not found")


@router.get("/chores/assignments", response_model=List[ChoreAssignmentOut])
async def list_chore_assignments(
    request: Request, week_start: Optional[date] = None
):
    _user_id(request)
    repo = get_bot_repo()
    ws = week_start or _week_start()
    members = [u["id"] for u in await _list_household_users()]
    assignments = await repo.regenerate_week_assignments(ws, members)
    # Re-fetch to get the username field on rows that were already cached.
    return await repo.list_assignments_for_week(ws)


@router.put(
    "/chores/{chore_id}/assignments/{week_start}",
    response_model=ChoreAssignmentOut,
)
async def reassign_chore(
    request: Request,
    chore_id: int,
    week_start: date,
    user_id: int = Query(..., gt=0),
):
    _user_id(request)
    await get_bot_repo().upsert_assignment(chore_id, week_start, user_id)
    rows = await get_bot_repo().list_assignments_for_week(week_start)
    for row in rows:
        if row["chore_id"] == chore_id:
            return row
    raise HTTPException(status_code=500, detail="Reassignment dropped")


@router.put(
    "/chores/{chore_id}/assignments/{week_start}/completed",
    response_model=ChoreAssignmentOut,
)
async def set_chore_completed(
    request: Request,
    chore_id: int,
    week_start: date,
    body: ChoreCompletionUpdate,
):
    _user_id(request)
    row = await get_bot_repo().set_assignment_completed(
        chore_id, week_start, body.completed
    )
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found")
    rows = await get_bot_repo().list_assignments_for_week(week_start)
    for r in rows:
        if r["chore_id"] == chore_id:
            return r
    return row


# ---------------------------------------------------------------------------
# Audit sessions
# ---------------------------------------------------------------------------

@router.get("/audit/current", response_model=AuditSessionOut)
async def current_audit(request: Request):
    _user_id(request)
    return await get_bot_repo().get_or_create_audit_session()


@router.put("/audit/{week_start}", response_model=AuditSessionOut)
async def update_audit(
    request: Request, week_start: date, body: AuditSessionUpdate
):
    _user_id(request)
    patch = body.model_dump(exclude_unset=True)
    return await get_bot_repo().update_audit_session(week_start, patch)


@router.get("/audit", response_model=List[AuditSessionOut])
async def list_audit(request: Request, limit: int = Query(26, ge=1, le=104)):
    _user_id(request)
    return await get_bot_repo().list_audit_sessions(limit=limit)


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------

@router.get("/streaks", response_model=List[StreakOut])
async def list_streaks(request: Request):
    return await get_bot_repo().list_streaks(_user_id(request))


# ---------------------------------------------------------------------------
# Net-worth milestones
# ---------------------------------------------------------------------------

@router.get("/milestones", response_model=List[MilestoneOut])
async def list_milestones(request: Request):
    return await get_bot_repo().list_milestones(_user_id(request))


@router.post("/milestones", response_model=MilestoneOut, status_code=201)
async def add_milestone(request: Request, body: MilestoneCreate):
    return await get_bot_repo().add_milestone(
        _user_id(request), body.threshold_cents, body.label
    )


@router.delete("/milestones/{milestone_id}", status_code=204)
async def delete_milestone(request: Request, milestone_id: int):
    if not await get_bot_repo().delete_milestone(_user_id(request), milestone_id):
        raise HTTPException(status_code=404, detail="Milestone not found")


# ---------------------------------------------------------------------------
# Mood log
# ---------------------------------------------------------------------------

@router.get("/mood/recent", response_model=List[MoodEntryOut])
async def list_recent_moods(request: Request, limit: int = Query(50, ge=1, le=200)):
    return await get_bot_repo().list_recent_moods(_user_id(request), limit=limit)


@router.put("/mood/{transaction_id}")
async def upsert_mood(
    request: Request, transaction_id: int, body: MoodEntryUpsert
):
    user_id = _user_id(request)
    txn_repo = TransactionsRepository()
    txn = await txn_repo.get_transaction(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return await get_bot_repo().upsert_mood(
        transaction_id, user_id, body.mood, body.note
    )


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

@router.get("/receipts", response_model=List[ReceiptOut])
async def list_receipts(request: Request, limit: int = Query(40, ge=1, le=200)):
    user_id = _user_id(request)
    rows = await get_bot_repo().list_receipts(user_id, limit=limit)
    return [{**r, "lines": []} for r in rows]


@router.get("/receipts/{receipt_id}", response_model=ReceiptOut)
async def get_receipt(request: Request, receipt_id: int):
    user_id = _user_id(request)
    row = await get_bot_repo().get_receipt(user_id, receipt_id)
    if not row:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return row


@router.get("/receipts/{receipt_id}/image")
async def get_receipt_image(request: Request, receipt_id: int):
    user_id = _user_id(request)
    row = await get_bot_repo().get_receipt(user_id, receipt_id, with_image=True)
    if not row or not row.get("image_data"):
        raise HTTPException(status_code=404, detail="Receipt image not found")
    return Response(
        content=bytes(row["image_data"]),
        media_type=row.get("image_mime") or "image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.delete("/receipts/{receipt_id}", status_code=204)
async def delete_receipt(request: Request, receipt_id: int):
    user_id = _user_id(request)
    if not await get_bot_repo().delete_receipt(user_id, receipt_id):
        raise HTTPException(status_code=404, detail="Receipt not found")


# ---------------------------------------------------------------------------
# Couple leaderboard
# ---------------------------------------------------------------------------

@router.get("/leaderboard", response_model=LeaderboardOut)
async def get_leaderboard(request: Request):
    _user_id(request)
    return await get_bot_repo().get_weekly_leaderboard()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _list_household_users():
    """Households are small (you + partner). Used to build chore rotation."""
    from web.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, username FROM users ORDER BY id")
    return [dict(r) for r in rows]
