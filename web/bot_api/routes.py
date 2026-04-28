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
    BotActivityEntry,
    ChoreAssignmentOut,
    ChoreCompletionUpdate,
    ChoreCreate,
    ChoreOut,
    ChoreUpdate,
    CoupleSettingsOut,
    CoupleSettingsUpdate,
    HouseholdMember,
    LeaderboardOut,
    LinkedUser,
    MilestoneCreate,
    MilestoneOut,
    MoodEntryOut,
    MoodEntryUpsert,
    NotificationPrefOut,
    NotificationPrefUpdate,
    ReceiptLinesReplace,
    ReceiptOut,
    ReceiptUpdate,
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


def _is_owner(request: Request) -> bool:
    user = getattr(request.state, "user", None) or {}
    return bool(user.get("is_owner"))


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


@router.get("/telegram/linked-users", response_model=List[LinkedUser])
async def telegram_linked_users(request: Request):
    """Owner-only roster of every user with the bot wired up.

    Useful when one of the partners says "did you get the alert?" — the
    admin can confirm without poking at the DB. Non-owners get 403.
    """
    if not _is_owner(request):
        raise HTTPException(status_code=403, detail="Owner access required")
    return await get_bot_repo().list_linked_users()


@router.get("/household-members", response_model=List[HouseholdMember])
async def household_members(request: Request):
    """Real household members — excludes the env-var bootstrap admin.

    Used by the Chores tab assignee dropdown and the Audit host picker so
    the technical admin account never shows up as someone who has to take
    out the trash.
    """
    _user_id(request)
    return await get_bot_repo().list_household_members()


@router.post("/telegram/test")
async def telegram_send_test(request: Request):
    """Probe the full notification pipeline.

    Enqueues a P0 ``test_alert`` row for the caller's user_id and kicks
    off a background drain. We deliberately do NOT ``await`` the drain
    inside the request — the dispatcher iterates every linked user and
    talks to Telegram, which can take several seconds and would tie up
    the request socket. The scheduled minute-tick is the safety net if
    the background task can't acquire the pool quickly.

    Response shape:
      ``{sent: true, queued_id: N}``        — row enqueued, drain kicked
      ``{sent: false, deduped: true}``      — same key already in flight
      503 with detail "queue write timed out" — DB was unresponsive
    """
    import asyncio as _asyncio

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
    try:
        # Cap enqueue at 10s — well under the pool's command_timeout (30s)
        # so a slow Postgres surfaces a friendly error here instead of a
        # generic 500. The row almost always lands fast; this guard is for
        # the rare lock-contention / Railway-routing hiccups.
        new_id = await _asyncio.wait_for(
            enqueue_notification(
                user_id=user_id,
                type="test_alert",
                priority="P0",
                payload={"requested_by": user.get("username") or "user"},
                # Per-second dedup so a button mash doesn't spam, but each
                # legitimate click goes through.
                dedup_key=dedup_key_for(
                    "test_alert",
                    user_id,
                    datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
                ),
            ),
            timeout=10,
        )
    except _asyncio.TimeoutError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Queue write timed out. The DB looks slow — try again "
                "in a moment. If it persists check Railway logs for "
                "lock contention."
            ),
        )
    if new_id is None:
        return {"sent": False, "deduped": True}
    # Fire-and-forget drain so the user doesn't wait on the Telegram round
    # trip; the scheduled 60s tick is the safety net.
    _asyncio.create_task(trigger_drain_now())
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
async def delete_receipt(
    request: Request,
    receipt_id: int,
    delete_linked_cash: bool = Query(
        False,
        description=(
            "When true and the receipt is attached to a manual cash "
            "transaction, that transaction is removed in the same DB "
            "transaction. Bank-imported transactions are never deleted "
            "by this path — Plaid is the source of truth."
        ),
    ),
):
    user_id = _user_id(request)
    if not await get_bot_repo().delete_receipt(
        user_id, receipt_id, delete_linked_cash=delete_linked_cash
    ):
        raise HTTPException(status_code=404, detail="Receipt not found")


@router.patch("/receipts/{receipt_id}", response_model=ReceiptOut)
async def update_receipt(
    request: Request,
    receipt_id: int,
    patch: ReceiptUpdate,
):
    """Edit OCR-derived header fields when the model got something wrong.

    Pydantic's ``model_dump(exclude_unset=True)`` keeps the SQL UPDATE
    surgical: a request that only sets ``total_cents`` won't blank out
    the merchant.
    """
    user_id = _user_id(request)
    diff = patch.model_dump(exclude_unset=True)
    receipt = await get_bot_repo().update_receipt(user_id, receipt_id, diff)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return receipt


@router.put("/receipts/{receipt_id}/lines", response_model=ReceiptOut)
async def replace_receipt_lines(
    request: Request,
    receipt_id: int,
    body: ReceiptLinesReplace,
):
    """Replace the entire line-items list (delete + re-insert).

    Replace-all is intentional — the FE always edits the whole list at
    once, and avoiding per-line PATCH endpoints keeps the API surface
    small. ``line_number`` is rebuilt from array position so reordering
    works for free.
    """
    user_id = _user_id(request)
    lines = [line.model_dump() for line in body.lines]
    receipt = await get_bot_repo().replace_receipt_lines(user_id, receipt_id, lines)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return receipt


@router.get("/receipts/by-transaction/{transaction_id}", response_model=ReceiptOut)
async def get_receipt_by_transaction(request: Request, transaction_id: int):
    """Look up the receipt attached to a specific transaction.

    Used by the transactions detail modal to surface the receipt
    breakdown next to the bank line. Returns 404 if no receipt is
    linked. Schema permits multiple receipts per tx but we return the
    most recent — real-world flows are 1:1 today.
    """
    user_id = _user_id(request)
    receipt = await get_bot_repo().get_receipt_by_transaction(user_id, transaction_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="No receipt for this transaction")
    return receipt


@router.patch("/receipts/{receipt_id}/link", response_model=ReceiptOut)
async def link_receipt(
    request: Request,
    receipt_id: int,
    transaction_id: Optional[int] = Query(
        None, description="Pass null/omit to detach the receipt."
    ),
    delete_linked_cash: bool = Query(
        False,
        description=(
            "When detaching a receipt that was previously attached to a "
            "manual cash transaction, also delete that cash row. "
            "Prevents the 'log as cash → re-attach to Plaid → cash row "
            "stuck in wallet' double-counting pattern."
        ),
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
        txn = await TransactionsRepository().get_transaction(int(transaction_id))
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")
    receipt = await get_bot_repo().link_receipt(
        user_id, receipt_id, transaction_id, delete_linked_cash=delete_linked_cash
    )
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
# Bot activity log — surfaced in the frontend Bot → Activity tab so the
# user doesn't need to read Railway logs to diagnose a misbehaving bot.
# ---------------------------------------------------------------------------

@router.get("/activity", response_model=List[BotActivityEntry])
async def list_bot_activity(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    severity: Optional[str] = Query(
        None,
        regex=r"^(info|warn|error)$",
        description="Filter to one severity bucket.",
    ),
    kind_prefix: Optional[str] = Query(
        None,
        max_length=40,
        description=(
            "Filter to a kind prefix, e.g. `error`, `outgoing.`, `ocr.`, "
            "`incoming.`."
        ),
    ),
    scope: str = Query(
        "self",
        regex=r"^(self|all)$",
        description=(
            "`self` shows the caller's own rows; `all` shows every user's "
            "rows (owner-only, used by the admin view)."
        ),
    ),
):
    """Recent bot events. ``user_id IS NULL`` rows (errors from unlinked
    chats) are returned to every authenticated user — they're rare and
    everyone benefits from seeing the bot exploded somewhere.

    Owners can pass ``scope=all`` to see rows attributed to other users —
    handy for the admin view that surfaces what the bot did for the whole
    household."""
    user_id = _user_id(request)
    from web.telegram.activity import list_activity

    filter_uid: Optional[int] = user_id
    if scope == "all":
        if not _is_owner(request):
            raise HTTPException(
                status_code=403,
                detail="Cross-user activity scope requires owner access.",
            )
        filter_uid = None

    rows = await list_activity(
        limit=limit,
        severity=severity,
        kind_prefix=kind_prefix,
        user_id=filter_uid,
    )
    return rows


@router.delete("/activity", status_code=204)
async def clear_bot_activity(
    request: Request,
    older_than_days: int = Query(
        0,
        ge=0,
        le=365,
        description=(
            "Delete rows older than N days (0 = clear ALL the caller's "
            "activity history)."
        ),
    ),
):
    """Manual prune. Daily auto-prune at 30 days runs in the dispatcher."""
    user_id = _user_id(request)
    from web.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        if older_than_days == 0:
            await conn.execute(
                "DELETE FROM bot_activity_log WHERE user_id = $1 OR user_id IS NULL",
                user_id,
            )
        else:
            await conn.execute(
                """
                DELETE FROM bot_activity_log
                WHERE (user_id = $1 OR user_id IS NULL)
                  AND created_at < NOW() - make_interval(days => $2)
                """,
                user_id,
                int(older_than_days),
            )


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
