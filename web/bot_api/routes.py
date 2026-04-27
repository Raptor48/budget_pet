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


@router.post("/telegram/test")
async def telegram_send_test(request: Request):
    """Probe the full notification pipeline.

    Enqueues a P0 ``test_alert`` row for the caller's user_id, then forces
    the dispatcher to drain immediately so the round-trip latency is just
    "Telegram API + your phone push" rather than the regular 60s tick.

    Response surfaces ``{sent: true}`` if the dispatcher claimed the row;
    failures live in ``notifications_queue.failed_at`` and the FastAPI
    logs (search for ``Failed to send P0 notification``).
    """
    user_id = _user_id(request)
    status = await get_bot_repo().get_telegram_link_status(user_id)
    if not status.get("linked"):
        raise HTTPException(
            status_code=412,
            detail=(
                "This account isn't linked to Telegram yet. Generate a "
                "code on the Bot → Overview tab and run /link in the bot."
            ),
        )
    from web.notifications.dispatcher import trigger_drain_now
    from web.notifications.queue import (
        dedup_key_for,
        enqueue_notification,
    )

    user = getattr(request.state, "user", None) or {}
    new_id = await enqueue_notification(
        user_id=user_id,
        type="test_alert",
        priority="P0",
        payload={"requested_by": user.get("username") or "user"},
        # Per-second dedup so the user can mash the button without spam,
        # but a single click always goes through.
        dedup_key=dedup_key_for(
            "test_alert",
            user_id,
            datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        ),
    )
    if new_id is None:
        return {"sent": False, "deduped": True}
    await trigger_drain_now()
    return {"sent": True, "queued_id": new_id}


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


@router.patch("/receipts/{receipt_id}/link", response_model=ReceiptOut)
async def link_receipt(
    request: Request,
    receipt_id: int,
    transaction_id: Optional[int] = Query(
        None, description="Pass null/omit to detach the receipt."
    ),
):
    """Attach (or detach with ``transaction_id=null``) a receipt to a tx.

    The receipt's amount/date should already be reasonable; we don't try to
    enforce a strict match here so the user can override fuzzy cases (e.g.
    Plaid posted $84.32 but the paper receipt says $84.31 because of a
    rounding glitch on the bank's side).
    """
    user_id = _user_id(request)
    if transaction_id is not None:
        # Verify the target transaction exists at all (gives a friendly 404
        # instead of a silent no-op when the user pastes the wrong id).
        from web.transactions.repo import TransactionsRepository

        txn = await TransactionsRepository().get_transaction(int(transaction_id))
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")
    receipt = await get_bot_repo().link_receipt(user_id, receipt_id, transaction_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return receipt


@router.post("/receipts/{receipt_id}/log-as-cash", response_model=ReceiptOut)
async def log_receipt_as_cash(request: Request, receipt_id: int):
    """Create a cash transaction from the receipt's total + merchant and
    link the receipt to it. Used when the receipt is for a cash purchase
    that Plaid will never see."""
    user_id = _user_id(request)
    repo = get_bot_repo()
    receipt = await repo.get_receipt(user_id, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    if receipt.get("transaction_id"):
        raise HTTPException(
            status_code=409, detail="Receipt is already linked to a transaction."
        )
    amount_cents = int(receipt.get("total_cents") or 0)
    if amount_cents <= 0:
        raise HTTPException(
            status_code=422, detail="Receipt has no total to log as cash."
        )
    txn = await _create_cash_for_receipt(
        user_id=user_id,
        amount_cents=amount_cents,
        merchant=receipt.get("merchant_name"),
        receipt_date=receipt.get("receipt_date"),
    )
    await repo.attach_receipt_to_transaction(receipt_id, int(txn["id"]))
    return await repo.get_receipt(user_id, receipt_id)


async def _create_cash_for_receipt(
    *, user_id: int, amount_cents: int, merchant: Optional[str], receipt_date
):
    """Pick the user's primary cash wallet and write a manual cash tx."""
    from web.db import get_pool
    from web.transactions.repo import TransactionsRepository
    from datetime import date as _date

    pool = await get_pool()
    async with pool.acquire() as conn:
        wallet = await conn.fetchrow(
            """
            SELECT id FROM accounts
            WHERE plaid_account_id IS NULL AND is_active = TRUE
              AND (user_id = $1 OR user_id IS NULL)
            ORDER BY (user_id = $1) DESC, id LIMIT 1
            """,
            user_id,
        )
    if not wallet:
        raise HTTPException(
            status_code=412,
            detail=(
                "No cash wallet found. Create one in the web app's "
                "Accounts page first."
            ),
        )
    return await TransactionsRepository().create_cash_transaction(
        {
            "account_id": wallet["id"],
            "amount_cents": amount_cents,
            "currency": "USD",
            "date": receipt_date or _date.today(),
            "name": merchant or "Receipt",
            "merchant_name": merchant,
            "source": "manual",
        }
    )


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
