"""
Notification dispatcher.

Runs every minute via APScheduler. For each user with a Telegram chat:

* P0 rows are sent immediately (skipping quiet hours).
* P1 rows accumulate and are flushed as ONE morning brief at the user's
  configured ``morning_brief_local`` time. Outside the brief window, P1
  rows simply wait — they are never sent piecemeal.
* P2 rows accumulate and are flushed once a week as the Sunday brief
  (composed alongside the morning brief on Sunday).

The whole loop is idempotent: ``mark_sent`` flips ``sent_at`` so the row
is excluded from the next pass — both for P0 sends and for the children
of a brief.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from web.bot_api.repo import get_bot_repo
from web.notifications import builders
from web.notifications.queue import (
    list_pending_for_user,
    mark_failed,
    mark_sent,
)

logger = logging.getLogger(__name__)

_JOB_ID = "notifications_dispatch"
_BRIEF_WINDOW_MINUTES = 15  # window within which a brief is considered "due"
_scheduler = None


# ---------------------------------------------------------------------------
# TZ helpers — best-effort, no external dependency. Falls back to UTC if the
# user provided a bogus timezone string.
# ---------------------------------------------------------------------------


def _user_now(tz_name: str) -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.now(timezone.utc)


def _is_in_quiet_hours(now_local: datetime, start: time, end: time) -> bool:
    """Quiet hours can wrap past midnight (e.g. 22:00–08:00)."""
    cur = now_local.time()
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


def _within_brief_window(now_local: datetime, brief_local: time) -> bool:
    today_brief = datetime.combine(
        now_local.date(), brief_local, tzinfo=now_local.tzinfo
    )
    delta = (now_local - today_brief).total_seconds() / 60
    return 0 <= delta < _BRIEF_WINDOW_MINUTES


# ---------------------------------------------------------------------------
# Telegram delivery
# ---------------------------------------------------------------------------


async def _send_to_chat(
    chat_id: int,
    text: str,
    keyboard: Optional[List[List[Any]]] = None,
) -> None:
    """Push a single message via the running bot. Raises on failure."""
    from web.telegram.runtime import get_bot_app

    app = get_bot_app()
    if app is None:
        raise RuntimeError("Telegram bot not initialised")
    reply_markup = None
    if keyboard:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        reply_markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(text=t, callback_data=cb) for t, cb in row]
                for row in keyboard
            ]
        )
    await app.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


# ---------------------------------------------------------------------------
# Drain
# ---------------------------------------------------------------------------


async def _drain_user(user_row: Dict[str, Any]) -> None:
    repo = get_bot_repo()
    user_id = user_row["id"]
    chat_id = user_row["telegram_chat_id"]
    settings = await repo.get_couple_settings(user_id)
    tz_name = settings["morning_brief_tz"]
    now_local = _user_now(tz_name)

    from web.telegram.activity import log_bot_activity

    # ------------------------------- P0: immediate
    p0 = await list_pending_for_user(user_id, priorities=["P0"])
    for n in p0:
        try:
            text, keyboard = builders.build_single(n)
            await _send_to_chat(chat_id, text, keyboard)
            await mark_sent([n["id"]])
            await log_bot_activity(
                kind="outgoing.push",
                summary=f"Sent P0 {n['type']}",
                user_id=user_id,
                chat_id=chat_id,
                payload={"queue_id": int(n["id"]), "type": n["type"]},
            )
        except Exception as exc:
            logger.exception("Failed to send P0 notification %s", n["id"])
            await mark_failed(n["id"], str(exc)[:300])
            await log_bot_activity(
                kind="outgoing.push",
                severity="error",
                summary=f"Failed to send P0 {n['type']}: {exc}"[:280],
                user_id=user_id,
                chat_id=chat_id,
                payload={"queue_id": int(n["id"]), "type": n["type"]},
                error=exc,
            )

    # ------------------------------- Briefs (P1, optionally P2)
    is_brief_due = _within_brief_window(now_local, settings["morning_brief_local"])
    in_quiet = _is_in_quiet_hours(
        now_local, settings["quiet_hours_start"], settings["quiet_hours_end"]
    )
    if not is_brief_due or in_quiet:
        return

    # Per-day idempotency: the dispatcher fires every minute and the brief
    # window is 15 minutes wide, so without this gate every minute inside
    # that window would compose and send a fresh brief. On weekdays the
    # "no pending rows ⇒ skip" check below would self-stop after the first
    # tick, but on Sunday the streak summary + audit invite always render
    # even with zero queue items — that's how the user ended up receiving
    # one Sunday brief per minute. Read the stamp set by the previous send.
    today_local = now_local.date()
    last_sent = settings.get("last_brief_sent_date")
    if last_sent == today_local:
        return

    is_sunday = now_local.weekday() == 6
    priorities = ["P1"]
    if is_sunday and settings.get("sunday_brief_enabled", True):
        priorities.append("P2")
    pending = await list_pending_for_user(user_id, priorities=priorities)
    if not pending and not is_sunday:
        return

    streak_summary = None
    audit_invite = None
    title = "Morning brief"
    if is_sunday and settings.get("sunday_brief_enabled", True):
        title = "Sunday brief"
        streak_summary = await repo.list_streaks(user_id)
        audit_invite = {"local_time": settings["morning_brief_local"].strftime("%H:%M")}
        # Bump the audit_weeks streak when we send the Sunday brief.
        try:
            await repo.bump_streak(user_id, "audit_weeks")
        except Exception:
            logger.exception("Failed to bump audit_weeks streak for user=%s", user_id)

    text, keyboard = builders.build_brief(
        title=title,
        notifications=pending,
        streak_summary=streak_summary,
        audit_invite=audit_invite,
    )
    if not text:
        return
    try:
        await _send_to_chat(chat_id, text, keyboard)
        # The brief is a one-shot Telegram message, not a queue row, so there
        # is no parent id to point children at. Just stamp sent_at — that
        # alone excludes them from the next tick (list_pending_for_user
        # already filters on sent_at IS NULL).
        await mark_sent([n["id"] for n in pending])
        # Stamp the per-day sentinel so subsequent ticks inside the same
        # local day skip out at the gate above. Best-effort — if the stamp
        # fails the worst case is the user gets one extra brief next minute
        # before the queue empties out, which beats failing the whole send.
        try:
            await repo.mark_brief_sent(user_id, now_local.date())
        except Exception:
            logger.exception(
                "Failed to stamp last_brief_sent_date for user=%s", user_id
            )
        await log_bot_activity(
            kind="outgoing.push",
            summary=f"Sent {title} ({len(pending)} item{'s' if len(pending) != 1 else ''})",
            user_id=user_id,
            chat_id=chat_id,
            payload={
                "title": title,
                "bundled_ids": [int(n["id"]) for n in pending],
            },
        )
    except Exception as exc:
        logger.exception("Failed to send brief for user=%s", user_id)
        # Don't fail the bundle — leave the rows untouched so we retry next
        # tick. Future improvement: exponential backoff.
        for n in pending:
            await mark_failed(n["id"], str(exc)[:300])
        await log_bot_activity(
            kind="outgoing.push",
            severity="error",
            summary=f"Failed to send {title}: {exc}"[:280],
            user_id=user_id,
            chat_id=chat_id,
            payload={"queued_ids": [int(n["id"]) for n in pending]},
            error=exc,
        )


async def _drain_once() -> None:
    repo = get_bot_repo()
    try:
        users = await repo.list_users_with_chat()
    except Exception:
        logger.exception("Failed to list users with chat ids")
        return
    for user in users:
        try:
            await _drain_user(user)
        except Exception:
            logger.exception("Drain failed for user=%s", user.get("id"))


# ---------------------------------------------------------------------------
# Scheduler bootstrap
# ---------------------------------------------------------------------------


async def _hourly_producers() -> None:
    """Top-up scan in case Plaid sync didn't run recently."""
    try:
        from web.notifications.producers import run_all_producers

        await run_all_producers()
    except Exception:
        logger.exception("Hourly producers tick failed")


async def _daily_warmup_frontend() -> None:
    """Daily HTTP ping of the Next.js frontend to keep its container warm.

    Why this exists:
      The FastAPI process is kept warm by this very dispatcher (one tick a
      minute). The Next.js container has no internal heartbeat — when the
      user doesn't open the web UI for a while, the first pageload hits a
      cold Node runtime + cold edge cache and can take ~30s.

      A single GET per day is enough to keep the container, the Railway
      edge router, and the TLS session warm without burning resources.

    Configuration:
      Reads ``PUBLIC_FRONTEND_URL`` (the same env var the bot uses to build
      Mini App / deep links). When unset — typical of local dev or a
      back-end-only deploy — the job no-ops.

    Failure handling:
      Best effort. Network errors, non-2xx responses, timeouts — all
      logged at INFO level (not error), because a warmup miss is harmless:
      the next user pageload will simply pay the cold-start cost once.
    """
    base = (os.getenv("PUBLIC_FRONTEND_URL") or "").strip().rstrip("/")
    if not base:
        logger.info("Daily warmup skipped: PUBLIC_FRONTEND_URL not set")
        return
    if "," in base:
        # Match handlers.py convention — first entry of a CSV list.
        base = base.split(",")[0].strip().rstrip("/")
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(base + "/")
        logger.info(
            "Daily warmup hit %s — status=%s", base, resp.status_code
        )
    except Exception as exc:
        logger.info("Daily warmup ping failed (harmless): %s", exc)


def start_dispatcher():
    """Start the per-minute dispatcher + hourly producer top-up.

    Idempotent: if called twice (rare in tests with reload), the second call
    just adds a unique-ID job and APScheduler dedups via ``replace_existing``.
    """
    global _scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
        _scheduler.start()
    _scheduler.add_job(
        _drain_once,
        trigger=IntervalTrigger(minutes=1),
        id=_JOB_ID,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    _scheduler.add_job(
        _hourly_producers,
        trigger=IntervalTrigger(hours=1),
        id="notifications_producers_hourly",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    # Daily prune of the two log surfaces. Window is 7 days when the
    # corresponding toggle on the app_settings row is on; the daily 30-day
    # safety cap on bot_activity_log stays in place even when the toggle
    # is off so storage can't grow without bound.
    _scheduler.add_job(
        _daily_prune_logs,
        trigger=IntervalTrigger(hours=24),
        id="bot_activity_log_prune",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    # Daily HTTP ping to keep the Next.js container & Railway edge warm
    # so the first morning pageload doesn't pay a 30s cold-start.
    _scheduler.add_job(
        _daily_warmup_frontend,
        trigger=IntervalTrigger(hours=24),
        id="frontend_daily_warmup",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    logger.info("Notification dispatcher running every 60s")
    return _scheduler


async def _daily_prune_logs() -> None:
    """Daily prune for both bot_activity_log and audit_log.

    Each side honours its own toggle on ``app_settings``:
      * ``bot_activity_auto_prune_enabled`` — 7d window when on; otherwise
        we still apply a 30-day safety cap so the table can't grow forever.
      * ``audit_log_auto_prune_enabled`` — 7d window when on; otherwise no
        prune (audit history is normally kept indefinitely).
    """
    try:
        from web.app_settings.repo import get_app_settings_repo

        settings = await get_app_settings_repo().get()
    except Exception:
        logger.exception("daily prune: failed to read app_settings")
        settings = {}

    # bot_activity_log
    try:
        from web.telegram.activity import prune_activity

        bot_window = (
            7 if bool(settings.get("bot_activity_auto_prune_enabled", True)) else 30
        )
        deleted = await prune_activity(older_than_days=bot_window)
        if deleted:
            logger.info(
                "bot_activity_log: pruned %d rows older than %dd",
                deleted,
                bot_window,
            )
    except Exception:
        logger.exception("bot_activity_log prune failed")

    # audit_log — only when explicitly opted in
    if bool(settings.get("audit_log_auto_prune_enabled", False)):
        try:
            from web.audit.repo import get_audit_repo
            from datetime import datetime, timedelta, timezone as _tz

            cutoff = datetime.now(_tz.utc) - timedelta(days=7)
            from web.db import get_pool

            pool = await get_pool()
            async with pool.acquire() as conn:
                # Use direct SQL so we bound by created_at, not the id
                # cursor that AuditRepository.delete supports.
                status = await conn.execute(
                    "DELETE FROM audit_log WHERE created_at < $1", cutoff
                )
            deleted = 0
            try:
                deleted = int(status.split()[-1])
            except Exception:
                pass
            if deleted:
                logger.info("audit_log: pruned %d rows older than 7d", deleted)
        except Exception:
            logger.exception("audit_log prune failed")


async def trigger_drain_now() -> None:
    """Manually drain (used by tests + the scheduler `force-sync` path)."""
    await _drain_once()
