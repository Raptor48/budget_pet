"""
FastAPI route for the Telegram webhook.

The path ``/api/telegram/webhook`` is excluded from session auth in
:mod:`web.auth.middleware` (TBD — see middleware patch below). Telegram
authenticates each call via the secret token header
``X-Telegram-Bot-Api-Secret-Token`` which we compare to
``TELEGRAM_WEBHOOK_SECRET`` in constant time.

Idempotency: Telegram guarantees *at-least-once* delivery. Any update
``update_id`` we acknowledged but Telegram didn't see the 200 for (cold
start, network blip, container restart) is replayed. We dedup by
``update_id`` against the ``telegram_seen_updates`` table — first hit
processes, second hit returns 200 without invoking handlers.
"""
from __future__ import annotations

import hmac
import logging
import os
import time

from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


# Heartbeat counters — observable via /api/telegram/health. Plain
# module-level mutables because the bot runs in-process inside a single
# uvicorn worker; if/when we shard, switch this to Redis/DB.
_LAST_UPDATE_AT: float | None = None
_LAST_UPDATE_ID: int | None = None
_DUPLICATE_UPDATES_SEEN: int = 0


def _expected_secret() -> str:
    return (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()


async def _claim_update_id(update_id: int) -> bool:
    """Insert the ``update_id`` into the dedup table. Returns ``True`` if
    this is the first time we've seen it (caller should process), ``False``
    if it was already processed (caller should return 200 without doing
    anything).

    Failures (DB down, table missing) fall through to ``True`` — better to
    risk a duplicate than to silently drop a real update. The startup
    migration creates the table, so the only way this errors is during
    early boot before migrations finished.
    """
    try:
        from web.db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO telegram_seen_updates (update_id)
                VALUES ($1)
                ON CONFLICT (update_id) DO NOTHING
                RETURNING update_id
                """,
                int(update_id),
            )
            return row is not None
    except Exception:
        logger.exception(
            "telegram_seen_updates check failed; processing update %s anyway",
            update_id,
        )
        return True


@router.post("/webhook")
async def telegram_webhook(request: Request):
    global _LAST_UPDATE_AT, _LAST_UPDATE_ID, _DUPLICATE_UPDATES_SEEN

    secret = _expected_secret()
    if not secret:
        # Bot disabled — just 200 so Telegram doesn't keep retrying. We log
        # at WARNING so misconfigured prod is still loud.
        logger.warning("Telegram webhook hit but TELEGRAM_WEBHOOK_SECRET not set")
        return Response(status_code=200)
    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
    if not hmac.compare_digest(header_secret, secret):
        raise HTTPException(status_code=403, detail="Forbidden")

    from telegram import Update

    from .runtime import get_bot_app

    app = get_bot_app()
    if app is None:
        logger.warning("Webhook hit but bot runtime is not initialized")
        return Response(status_code=200)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    update_id = body.get("update_id") if isinstance(body, dict) else None
    if isinstance(update_id, int):
        first_time = await _claim_update_id(update_id)
        if not first_time:
            # Telegram retried an update we already processed. Acknowledge
            # silently so it stops retrying — handlers must not run twice.
            _DUPLICATE_UPDATES_SEEN += 1
            logger.info(
                "Skipping duplicate Telegram update_id=%s (total dupes=%s)",
                update_id,
                _DUPLICATE_UPDATES_SEEN,
            )
            return Response(status_code=200)

    try:
        update = Update.de_json(body, app.bot)
    except Exception:
        logger.exception("Failed to parse Telegram update")
        return Response(status_code=200)
    try:
        await app.process_update(update)
    except Exception:
        logger.exception("Update handler crashed")

    _LAST_UPDATE_AT = time.time()
    if isinstance(update_id, int):
        _LAST_UPDATE_ID = update_id

    return Response(status_code=200)


@router.get("/health")
async def telegram_health():
    """Public-ish liveness for the bot subsystem.

    Surfaces three signals an external uptime monitor (or the owner) can
    poll without touching DB:

    * ``configured`` — webhook secret env var is present.
    * ``running``    — :class:`telegram.ext.Application` initialized.
    * ``last_update_at`` / ``last_update_id`` — when the bot last
      processed something. Stale value (e.g. ``> 24h``) on an active
      household is the canonical "bot is silently dead" signal.
    * ``duplicate_updates_seen`` — sanity counter for the idempotency
      shield; non-zero is fine, growing fast hints at retry pressure.
    """
    from web.notifications.dispatcher import get_dispatcher_heartbeat

    from .runtime import get_bot_app

    app = get_bot_app()
    return {
        "configured": bool(_expected_secret()),
        "running": app is not None,
        "last_update_at": _LAST_UPDATE_AT,
        "last_update_id": _LAST_UPDATE_ID,
        "duplicate_updates_seen": _DUPLICATE_UPDATES_SEEN,
        "dispatcher": get_dispatcher_heartbeat(),
    }
