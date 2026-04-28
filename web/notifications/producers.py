"""
Notification producers — each function detects an alert condition and
``enqueue_notification`` it. They are deliberately read-only against the
domain repositories and write only to ``notifications_queue`` (+ a couple
of bot-only state tables for dedup/state).

Wired into the scheduler in :mod:`web.notifications.scheduler`.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

from web.bot_api.repo import get_bot_repo
from web.db import get_pool
from web.notifications.queue import dedup_key_for, enqueue_notification

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Budget threshold — fire when category crosses 100% of the monthly budget
# ---------------------------------------------------------------------------


async def detect_budget_thresholds() -> int:
    """Returns count of alerts enqueued."""
    pool = await get_pool()
    repo = get_bot_repo()
    today_month = date.today().strftime("%Y-%m")
    fired = 0
    async with pool.acquire() as conn:
        users = await conn.fetch(
            "SELECT id FROM users WHERE telegram_chat_id IS NOT NULL"
        )
        if not users:
            return 0
        rows = await conn.fetch(
            """
            WITH txn_totals AS (
                SELECT t.category_id,
                       SUM(t.amount_cents) AS spent_cents
                FROM transactions t
                WHERE TO_CHAR(t.date, 'YYYY-MM') = $1
                  AND COALESCE(t.transaction_class, 'expense') = 'expense'
                GROUP BY t.category_id
            )
            SELECT cb.category_id,
                   c.name AS category_name,
                   cb.budget_cents,
                   COALESCE(tt.spent_cents, 0) AS spent_cents
            FROM category_budgets cb
            JOIN categories c ON c.id = cb.category_id
            LEFT JOIN txn_totals tt ON tt.category_id = cb.category_id
            WHERE cb.month = $1
            """,
            today_month,
        )
    for r in rows:
        budget = int(r["budget_cents"] or 0)
        spent = int(r["spent_cents"] or 0)
        if budget <= 0 or spent < budget:
            continue
        pct = (spent / budget) * 100
        over = spent - budget
        for u in users:
            uid = int(u["id"])
            if not await repo.is_alert_enabled(uid, "budget_threshold"):
                continue
            new_id = await enqueue_notification(
                user_id=uid,
                type="budget_threshold",
                priority="P1",
                payload={
                    "category_name": r["category_name"],
                    "category_id": int(r["category_id"]),
                    "percent_used": pct,
                    "over_cents": over,
                    "budget_cents": budget,
                    "spent_cents": spent,
                    "month": today_month,
                },
                dedup_key=dedup_key_for(
                    "budget", today_month, int(r["category_id"])
                ),
            )
            if new_id:
                fired += 1
    return fired


# ---------------------------------------------------------------------------
# Recurring tomorrow — heads-up about a recurring charge tomorrow
# ---------------------------------------------------------------------------


async def detect_recurring_tomorrow() -> int:
    from web.reports.calculations import next_future_occurrence

    pool = await get_pool()
    repo = get_bot_repo()
    target = date.today() + timedelta(days=1)
    fired = 0
    async with pool.acquire() as conn:
        users = await conn.fetch(
            "SELECT id FROM users WHERE telegram_chat_id IS NOT NULL"
        )
        if not users:
            return 0
        rows = await conn.fetch(
            """
            SELECT id, description, frequency, average_amount_cents, last_date
            FROM recurring_streams
            WHERE is_active = TRUE
              AND user_status = 'active'
              AND last_date IS NOT NULL
            """,
        )
    for r in rows:
        # Advance from last_date to the next *future* expected charge using
        # the same helper the FE/forecast use. Plaid's last_date can be
        # several cadences behind, so a single +1 month is wrong.
        nxt = next_future_occurrence(r["last_date"], r["frequency"] or "")
        if nxt != target:
            continue
        for u in users:
            uid = int(u["id"])
            if not await repo.is_alert_enabled(uid, "recurring_tomorrow"):
                continue
            new_id = await enqueue_notification(
                user_id=uid,
                type="recurring_tomorrow",
                priority="P1",
                payload={
                    "name": r["description"],
                    "amount_cents": int(r["average_amount_cents"] or 0),
                    "due_date": str(target),
                },
                dedup_key=dedup_key_for("recurring_tomorrow", int(r["id"]), target),
            )
            if new_id:
                fired += 1
    return fired


# ---------------------------------------------------------------------------
# Plaid reauth — fire when an item flips to login_required
# ---------------------------------------------------------------------------


async def detect_plaid_reauth() -> int:
    pool = await get_pool()
    repo = get_bot_repo()
    fired = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT pi.item_id, pi.institution_name, pi.user_id
            FROM plaid_items pi
            WHERE pi.item_login_required = TRUE
            """,
        )
        users = await conn.fetch(
            "SELECT id FROM users WHERE telegram_chat_id IS NOT NULL"
        )
    for r in rows:
        target_user_ids = (
            [int(r["user_id"])] if r["user_id"] else [int(u["id"]) for u in users]
        )
        for uid in target_user_ids:
            if not await repo.is_alert_enabled(uid, "plaid_reauth"):
                continue
            new_id = await enqueue_notification(
                user_id=uid,
                type="plaid_reauth",
                priority="P0",
                payload={
                    "item_id": r["item_id"],
                    "institution_name": r["institution_name"] or "Bank",
                },
                dedup_key=dedup_key_for("reauth", r["item_id"]),
            )
            if new_id:
                fired += 1
    return fired


# ---------------------------------------------------------------------------
# New merchant — fired once per merchant_key, scanned per user so a private
# transaction (transactions.is_private=true) can't surface its merchant to
# the partner who doesn't own that account.
# ---------------------------------------------------------------------------


async def detect_new_merchants() -> int:
    pool = await get_pool()
    repo = get_bot_repo()
    fired = 0
    async with pool.acquire() as conn:
        users = await conn.fetch(
            "SELECT id FROM users WHERE telegram_chat_id IS NOT NULL"
        )
        if not users:
            return 0
        # Build a per-merchant view of who owns the underlying account, so we
        # can decide which users may legitimately see the alert.
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (lower(t.merchant_name))
                   t.merchant_name,
                   t.amount_cents,
                   t.date,
                   t.is_private,
                   a.user_id AS account_owner_id
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE t.merchant_name IS NOT NULL
              AND t.merchant_name <> ''
              AND t.date >= CURRENT_DATE - INTERVAL '2 days'
              AND COALESCE(t.transaction_class, 'expense') = 'expense'
            ORDER BY lower(t.merchant_name), t.date DESC
            """,
        )
    for r in rows:
        merchant = (r["merchant_name"] or "").strip()
        if not merchant:
            continue
        key = merchant.lower()
        sighting = await repo.remember_merchant(key)
        if not sighting.get("new"):
            continue
        await repo.mark_merchant_notified(key)
        # If the source transaction is private, the only user allowed to be
        # alerted is whoever owns the account it's on. Otherwise everyone
        # with a linked Telegram chat may see it.
        is_private = bool(r["is_private"])
        owner_id = r["account_owner_id"]
        if is_private:
            target_ids = [int(owner_id)] if owner_id is not None else []
        else:
            target_ids = [int(u["id"]) for u in users]
        for uid in target_ids:
            if not await repo.is_alert_enabled(uid, "new_merchant"):
                continue
            new_id = await enqueue_notification(
                user_id=uid,
                type="new_merchant",
                priority="P1",
                payload={
                    "merchant_name": merchant,
                    "amount_cents": int(r["amount_cents"] or 0),
                },
                dedup_key=dedup_key_for("new_merchant", key, uid),
            )
            if new_id:
                fired += 1
    return fired


# ---------------------------------------------------------------------------
# Subscription creep + price hike — leverage recurring_price_snapshots
# ---------------------------------------------------------------------------


async def detect_subscription_changes() -> int:
    pool = await get_pool()
    repo = get_bot_repo()
    fired = 0
    async with pool.acquire() as conn:
        streams = await conn.fetch(
            """
            SELECT id, description, last_amount_cents
            FROM recurring_streams
            WHERE is_active = TRUE AND user_status = 'active'
              AND last_amount_cents IS NOT NULL
            """,
        )
        users = await conn.fetch(
            "SELECT id FROM users WHERE telegram_chat_id IS NOT NULL"
        )
    for s in streams:
        history = await repo.get_recurring_price_history(int(s["id"]), limit=2)
        prev_amount = None
        if history:
            # Most recent snapshot (history[0]) is the current; check if there
            # is an earlier one to compare against.
            if len(history) >= 2:
                prev_amount = int(history[1]["amount_cents"])
        # Always record the current price; helper is no-op when unchanged.
        await repo.record_recurring_amount(
            int(s["id"]), int(s["last_amount_cents"])
        )
        # Brand-new stream → "subscription_creep" with prev=None.
        # Existing stream that just changed → "subscription_creep" with prev set.
        if prev_amount == int(s["last_amount_cents"]):
            continue
        for u in users:
            uid = int(u["id"])
            if not await repo.is_alert_enabled(uid, "subscription_creep"):
                continue
            new_id = await enqueue_notification(
                user_id=uid,
                type="subscription_creep",
                priority="P1",
                payload={
                    "name": s["description"],
                    "amount_cents": int(s["last_amount_cents"]),
                    "previous_amount_cents": prev_amount,
                    "stream_id": int(s["id"]),
                },
                dedup_key=dedup_key_for(
                    "subscription_creep",
                    int(s["id"]),
                    int(s["last_amount_cents"]),
                ),
            )
            if new_id:
                fired += 1
    return fired


# ---------------------------------------------------------------------------
# Net-worth milestones — household-wide. When the family net worth crosses
# a threshold, every linked user gets one alert; the row is marked reached
# globally so subsequent passes skip it.
# ---------------------------------------------------------------------------


async def detect_milestones() -> int:
    pool = await get_pool()
    repo = get_bot_repo()
    fired = 0
    async with pool.acquire() as conn:
        snapshot = await conn.fetchrow(
            "SELECT net_worth_cents FROM net_worth_snapshots ORDER BY snapshot_date DESC LIMIT 1"
        )
    if not snapshot:
        return 0
    net = int(snapshot["net_worth_cents"])
    async with pool.acquire() as conn:
        users = await conn.fetch(
            "SELECT id FROM users WHERE telegram_chat_id IS NOT NULL"
        )
    if not users:
        return 0
    # Iterate every household milestone once (de-duped by threshold so
    # rows added by different partners at the same threshold collapse to
    # one celebration). Whoever's row we mark first carries the
    # ``reached_at`` flag, but ``mark_milestone_reached`` updates every
    # matching row to keep listings consistent.
    seen_thresholds: set[int] = set()
    for m in await repo.list_milestones():
        threshold = int(m["threshold_cents"])
        if threshold in seen_thresholds:
            continue
        seen_thresholds.add(threshold)
        if m["reached_at"]:
            continue
        if net < threshold:
            continue
        await repo.mark_milestone_reached(None, threshold)
        for u in users:
            uid = int(u["id"])
            if not await repo.is_alert_enabled(uid, "milestone"):
                continue
            new_id = await enqueue_notification(
                user_id=uid,
                type="milestone",
                priority="P1",
                payload={
                    "threshold_cents": threshold,
                    "label": m.get("label"),
                    "current_cents": net,
                },
                dedup_key=dedup_key_for("milestone", uid, threshold),
            )
            if new_id:
                fired += 1
    return fired


# ---------------------------------------------------------------------------
# Mood check — bundled into morning brief, never wakes the user
# ---------------------------------------------------------------------------


async def detect_mood_check() -> int:
    pool = await get_pool()
    repo = get_bot_repo()
    fired = 0
    async with pool.acquire() as conn:
        users = await conn.fetch(
            "SELECT id FROM users WHERE telegram_chat_id IS NOT NULL"
        )
        if not users:
            return 0
        for u in users:
            uid = int(u["id"])
            if not await repo.is_alert_enabled(uid, "mood_check"):
                continue
            settings = await repo.get_couple_settings(uid)
            threshold = int(settings.get("mood_threshold_cents") or 0)
            if threshold <= 0:
                continue
            # Only ask the user about transactions on accounts they own —
            # otherwise we'd nudge the partner about a purchase they didn't
            # make (and possibly leak a private one). is_private is enforced
            # by the same account-ownership join.
            row = await conn.fetchrow(
                """
                SELECT t.id, t.amount_cents,
                       COALESCE(t.display_title, t.name) AS name
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                LEFT JOIN transaction_mood m ON m.transaction_id = t.id
                WHERE m.transaction_id IS NULL
                  AND t.amount_cents >= $1
                  AND COALESCE(t.transaction_class, 'expense') = 'expense'
                  AND t.date >= CURRENT_DATE - INTERVAL '2 days'
                  AND a.user_id = $2
                  AND (NOT t.is_private OR a.user_id = $2)
                ORDER BY t.amount_cents DESC, t.id DESC
                LIMIT 1
                """,
                threshold,
                uid,
            )
            if not row:
                continue
            new_id = await enqueue_notification(
                user_id=uid,
                type="mood_check",
                priority="P1",
                payload={
                    "transaction_id": int(row["id"]),
                    "transaction_name": row["name"],
                    "amount_cents": int(row["amount_cents"]),
                },
                dedup_key=dedup_key_for("mood_check", uid, int(row["id"])),
            )
            if new_id:
                fired += 1
    return fired


# ---------------------------------------------------------------------------
# Anniversary — fires 7 days before and on the day itself.
# ---------------------------------------------------------------------------


def _next_anniversary(original: date, today: date) -> date:
    """Project the original wedding date onto today's calendar.

    Handles Feb 29 by falling back to Feb 28 in non-leap years, so a leapling
    couple still gets a notification every year.
    """
    year = today.year
    try:
        candidate = original.replace(year=year)
    except ValueError:
        # Feb 29 in a non-leap year
        candidate = original.replace(year=year, day=28)
    if candidate < today:
        try:
            candidate = original.replace(year=year + 1)
        except ValueError:
            candidate = original.replace(year=year + 1, day=28)
    return candidate


async def detect_anniversary() -> int:
    pool = await get_pool()
    repo = get_bot_repo()
    fired = 0
    today = date.today()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT cs.user_id, cs.anniversary_date
              FROM couple_settings cs
              JOIN users u ON u.id = cs.user_id
             WHERE cs.anniversary_date IS NOT NULL
               AND u.telegram_chat_id IS NOT NULL
            """,
        )
    for r in rows:
        original: date = r["anniversary_date"]
        next_anniv = _next_anniversary(original, today)
        days_until = (next_anniv - today).days
        # We fire two events: T-7 (heads-up) and T-0 (celebration).
        # Outside those two days nothing happens.
        if days_until not in (0, 7):
            continue
        uid = int(r["user_id"])
        if not await repo.is_alert_enabled(uid, "anniversary"):
            continue
        years = next_anniv.year - original.year
        new_id = await enqueue_notification(
            user_id=uid,
            type="anniversary",
            priority="P1",
            payload={
                "anniversary_date": str(next_anniv),
                "original_date": str(original),
                "years": years,
                "days_until": days_until,
            },
            dedup_key=dedup_key_for(
                "anniversary", uid, str(next_anniv), days_until
            ),
        )
        if new_id:
            fired += 1
    return fired


# ---------------------------------------------------------------------------
# Couple leaderboard — Sunday morning P2
# ---------------------------------------------------------------------------


async def emit_weekly_leaderboard() -> int:
    pool = await get_pool()
    repo = get_bot_repo()
    fired = 0
    board = await repo.get_weekly_leaderboard()
    if not board.get("entries"):
        return 0
    async with pool.acquire() as conn:
        users = await conn.fetch(
            "SELECT id FROM users WHERE telegram_chat_id IS NOT NULL"
        )
    week_key = str(board["week_start"])
    for u in users:
        uid = int(u["id"])
        if not await repo.is_alert_enabled(uid, "leaderboard"):
            continue
        # Honour the per-couple `leaderboard_enabled` setting in addition to
        # the alert-type toggle. The two are deliberately separate: one says
        # "I never want this notification" (alert pref), the other says
        # "we don't do the leaderboard ritual at all" (couple-level
        # opt-out). Either being false skips the push.
        couple = await repo.get_couple_settings(uid)
        if not couple.get("leaderboard_enabled", True):
            continue
        new_id = await enqueue_notification(
            user_id=uid,
            type="leaderboard",
            priority="P2",
            payload={
                "week_start": week_key,
                "entries": board["entries"],
            },
            dedup_key=dedup_key_for("leaderboard", week_key),
        )
        if new_id:
            fired += 1
    return fired


# ---------------------------------------------------------------------------
# Master "scan everything" — called from APScheduler hourly + after Plaid sync
# ---------------------------------------------------------------------------


async def run_all_producers() -> Dict[str, int]:
    results: Dict[str, int] = {}
    for name, fn in [
        ("budget_threshold", detect_budget_thresholds),
        ("recurring_tomorrow", detect_recurring_tomorrow),
        ("plaid_reauth", detect_plaid_reauth),
        ("new_merchant", detect_new_merchants),
        ("subscription_creep", detect_subscription_changes),
        ("milestone", detect_milestones),
        ("mood_check", detect_mood_check),
        ("anniversary", detect_anniversary),
    ]:
        try:
            results[name] = await fn()
        except Exception as exc:
            logger.exception("Producer %s failed: %s", name, exc)
            results[name] = -1
    return results


async def run_sunday_producers() -> Dict[str, int]:
    """Producers that should only fire on Sundays (or after weekly Plaid sync)."""
    results: Dict[str, int] = {}
    try:
        results["leaderboard"] = await emit_weekly_leaderboard()
    except Exception:
        logger.exception("Leaderboard producer failed")
        results["leaderboard"] = -1
    return results
