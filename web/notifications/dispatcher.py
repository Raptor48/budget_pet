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
    defer_many_until,
    defer_until,
    list_pending_for_user,
    mark_failed,
    mark_sent,
)

logger = logging.getLogger(__name__)

_JOB_ID = "notifications_dispatch"
_BRIEF_WINDOW_MINUTES = 15  # window within which a brief is considered "due"
# Per-user drain cap. Without it, a user with thousands of queued rows or
# a hung handler could block the whole loop. 30s is generous: a normal
# brief takes well under 1s and the per-tick cadence is 60s.
_DRAIN_USER_TIMEOUT_S = 30
_scheduler = None

# Heartbeat — surfaces via /api/telegram/health. The dispatcher silently
# stalling has been our worst flake; an external monitor pinging
# /health and watching ``last_drain_finished_at`` catches it without
# waiting for the user to notice missing briefs.
_LAST_DRAIN_STARTED_AT: Optional[float] = None
_LAST_DRAIN_FINISHED_AT: Optional[float] = None
_LAST_DRAIN_DURATION_S: Optional[float] = None
_LAST_DRAIN_USERS: int = 0


def get_dispatcher_heartbeat() -> Dict[str, Any]:
    """Snapshot of the most recent dispatcher tick. Lossy & in-process —
    if the bot moves to a multi-worker setup this needs to migrate to
    Redis or DB. Until then it's enough for a single-uvicorn deploy."""
    return {
        "last_drain_started_at": _LAST_DRAIN_STARTED_AT,
        "last_drain_finished_at": _LAST_DRAIN_FINISHED_AT,
        "last_drain_duration_s": _LAST_DRAIN_DURATION_S,
        "last_drain_users": _LAST_DRAIN_USERS,
    }


def _classify_telegram_error(exc: BaseException) -> str:
    """Map a Telegram-side exception to one of three buckets:

    * ``"permanent"`` — user blocked the bot, chat deactivated, etc.
      Never going to succeed; drop the row, mark the user blocked.
    * ``"retry_after"`` — Telegram 429. The exception carries a
      ``retry_after`` attribute we should honour.
    * ``"transient"`` — anything else (network blip, internal error).
      Mark failed for this attempt; producers will re-enqueue on the
      next tick if they still apply.

    Imported lazily so this module stays usable without python-telegram-bot.
    """
    try:
        from telegram.error import Forbidden, ChatMigrated, RetryAfter

        if isinstance(exc, Forbidden):
            return "permanent"
        if isinstance(exc, ChatMigrated):
            # The chat moved (group→supergroup migration). Treat like
            # "permanent" for this user_id; their record will be re-linked
            # on the next /start.
            return "permanent"
        if isinstance(exc, RetryAfter):
            return "retry_after"
    except ImportError:
        pass
    msg = str(exc).lower()
    if "blocked" in msg or "user is deactivated" in msg or "chat not found" in msg:
        return "permanent"
    return "transient"


def _retry_after_seconds(exc: BaseException) -> int:
    """Pull the ``retry_after`` from a Telegram ``RetryAfter`` exception,
    clamped to a sensible range. Telegram occasionally suggests very long
    backoffs (15+ min); honour them up to the dispatcher's tick cadence
    so we don't churn the row repeatedly."""
    val = getattr(exc, "retry_after", None)
    try:
        seconds = int(val) if val is not None else 60
    except (TypeError, ValueError):
        seconds = 60
    return max(15, min(seconds, 3600))


async def _mark_user_blocked(user_id: int) -> None:
    """Flip ``users.telegram_blocked = TRUE`` so the next tick skips this
    user. Idempotent (no-op if already TRUE). The user can re-link by
    sending ``/start`` again — :func:`web.bot_api.repo.attach_telegram_chat`
    flips the flag back to FALSE on attach."""
    try:
        from web.db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET telegram_blocked = TRUE WHERE id = $1",
                user_id,
            )
    except Exception:
        logger.exception("Failed to mark user=%s as telegram_blocked", user_id)


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
    # Skip users we've previously confirmed have blocked the bot. They get
    # un-blocked the next time they hit /start (attach_telegram_chat
    # clears the flag). Pulled defensively in case the DB column doesn't
    # exist yet (early-deploy race before migration).
    if user_row.get("telegram_blocked"):
        return
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
            kind = _classify_telegram_error(exc)
            if kind == "permanent":
                # User blocked the bot or the chat is gone. Mark the user
                # blocked once and drop the row so we don't keep retrying
                # every minute (1440 errors/day per blocked user).
                logger.info(
                    "Permanent Telegram error for user=%s; marking blocked: %s",
                    user_id,
                    exc,
                )
                await _mark_user_blocked(user_id)
                await mark_failed(n["id"], f"permanent:{exc}"[:300])
                await log_bot_activity(
                    kind="outgoing.push",
                    severity="warning",
                    summary=f"User blocked bot — stopping retries (P0 {n['type']})"[:280],
                    user_id=user_id,
                    chat_id=chat_id,
                    payload={"queue_id": int(n["id"]), "type": n["type"]},
                )
                # No further sends to this user this tick.
                return
            if kind == "retry_after":
                seconds = _retry_after_seconds(exc)
                logger.info(
                    "Telegram RetryAfter %ss for user=%s queue=%s",
                    seconds,
                    user_id,
                    n["id"],
                )
                await defer_until(n["id"], seconds)
                await log_bot_activity(
                    kind="outgoing.push",
                    severity="warning",
                    summary=f"Rate-limited; deferring P0 {n['type']} {seconds}s"[:280],
                    user_id=user_id,
                    chat_id=chat_id,
                    payload={
                        "queue_id": int(n["id"]),
                        "type": n["type"],
                        "retry_after_seconds": seconds,
                    },
                )
                # Stop draining this user — Telegram will say no to follow-ups.
                return
            # Transient — log error, mark this row failed, keep going.
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
        kind = _classify_telegram_error(exc)
        ids = [int(n["id"]) for n in pending]
        if kind == "permanent":
            logger.info(
                "Permanent Telegram error for user=%s during %s; marking blocked: %s",
                user_id,
                title,
                exc,
            )
            await _mark_user_blocked(user_id)
            for n in pending:
                await mark_failed(n["id"], f"permanent:{exc}"[:300])
            await log_bot_activity(
                kind="outgoing.push",
                severity="warning",
                summary=f"User blocked bot — stopping retries ({title})"[:280],
                user_id=user_id,
                chat_id=chat_id,
                payload={"queued_ids": ids},
            )
            return
        if kind == "retry_after":
            seconds = _retry_after_seconds(exc)
            logger.info(
                "Telegram RetryAfter %ss on %s for user=%s",
                seconds,
                title,
                user_id,
            )
            # Defer the whole bundle so the next tick won't re-attempt
            # before Telegram is ready. We don't stamp last_brief_sent_date
            # — the brief actually didn't go out — so when the embargo lifts
            # the next dispatcher tick within the brief window will retry.
            await defer_many_until(ids, seconds)
            await log_bot_activity(
                kind="outgoing.push",
                severity="warning",
                summary=f"Rate-limited; deferring {title} {seconds}s"[:280],
                user_id=user_id,
                chat_id=chat_id,
                payload={
                    "queued_ids": ids,
                    "retry_after_seconds": seconds,
                },
            )
            return
        logger.exception("Failed to send brief for user=%s", user_id)
        # Transient: leave the rows untouched so we retry next tick. The
        # error string still surfaces in the activity log for debugging.
        for n in pending:
            await mark_failed(n["id"], str(exc)[:300])
        await log_bot_activity(
            kind="outgoing.push",
            severity="error",
            summary=f"Failed to send {title}: {exc}"[:280],
            user_id=user_id,
            chat_id=chat_id,
            payload={"queued_ids": ids},
            error=exc,
        )


async def _drain_once() -> None:
    """One dispatcher tick: drain every user with a Telegram chat.

    Each user's drain is bounded by ``_DRAIN_USER_TIMEOUT_S`` so a single
    hung handler can't stall the whole loop (the prior failure mode: a
    50-row brief send hanging for 90s while ``max_instances=1`` blocks
    the next tick from starting).
    """
    global _LAST_DRAIN_STARTED_AT, _LAST_DRAIN_FINISHED_AT
    global _LAST_DRAIN_DURATION_S, _LAST_DRAIN_USERS
    import time as _time

    started = _time.time()
    _LAST_DRAIN_STARTED_AT = started
    repo = get_bot_repo()
    try:
        users = await repo.list_users_with_chat()
    except Exception:
        logger.exception("Failed to list users with chat ids")
        # Still mark the tick as "finished" — a DB blip shouldn't make the
        # heartbeat look stale. Health check will surface the underlying
        # error via logs.
        _LAST_DRAIN_FINISHED_AT = _time.time()
        _LAST_DRAIN_DURATION_S = _LAST_DRAIN_FINISHED_AT - started
        _LAST_DRAIN_USERS = 0
        return
    drained = 0
    for user in users:
        try:
            await asyncio.wait_for(_drain_user(user), timeout=_DRAIN_USER_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.error(
                "Drain timed out (>%ss) for user=%s — moving on",
                _DRAIN_USER_TIMEOUT_S,
                user.get("id"),
            )
        except Exception:
            logger.exception("Drain failed for user=%s", user.get("id"))
        drained += 1
    _LAST_DRAIN_FINISHED_AT = _time.time()
    _LAST_DRAIN_DURATION_S = _LAST_DRAIN_FINISHED_AT - started
    _LAST_DRAIN_USERS = drained


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
