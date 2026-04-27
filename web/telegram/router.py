"""
FastAPI route for the Telegram webhook.

The path ``/api/telegram/webhook`` is excluded from session auth in
:mod:`web.auth.middleware` (TBD — see middleware patch below). Telegram
authenticates each call via the secret token header
``X-Telegram-Bot-Api-Secret-Token`` which we compare to
``TELEGRAM_WEBHOOK_SECRET`` in constant time.
"""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


def _expected_secret() -> str:
    return (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()


@router.post("/webhook")
async def telegram_webhook(request: Request):
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
    try:
        update = Update.de_json(body, app.bot)
    except Exception:
        logger.exception("Failed to parse Telegram update")
        return Response(status_code=200)
    try:
        await app.process_update(update)
    except Exception:
        logger.exception("Update handler crashed")
    return Response(status_code=200)


@router.get("/health")
async def telegram_health():
    from .runtime import get_bot_app

    app = get_bot_app()
    return {
        "configured": bool(_expected_secret()),
        "running": app is not None,
    }
