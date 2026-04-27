"""
Telegram bot runtime — webhook mode.

We don't run :class:`telegram.ext.Application.start_polling`; instead the
FastAPI webhook handler calls ``app.process_update(update)`` directly so the
bot is just another router in the same uvicorn worker.

``start_bot_runtime`` is idempotent — safe to call from FastAPI's startup
hook on every reload.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_app = None  # telegram.ext.Application


def _token() -> Optional[str]:
    return (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() or None


def get_bot_app():
    return _app


async def start_bot_runtime():
    """Build the Application, register handlers, and call ``initialize`` /
    ``start`` so outgoing messages can be sent without a polling loop.

    Webhook installation (calling ``setWebhook``) is left to operations: the
    URL might be unknown at startup (Railway preview deploys), and we don't
    want to overwrite a working webhook on every redeploy. Instructions live
    in ``docs/bot.md``.
    """
    global _app
    token = _token()
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN unset — skipping bot runtime init")
        return None
    if _app is not None:
        return _app

    from telegram.ext import Application

    builder = Application.builder().token(token)
    application = builder.build()

    from .handlers import register_handlers

    register_handlers(application)

    await application.initialize()
    await application.start()
    _app = application
    logger.info("Telegram bot runtime initialized")
    return _app


async def stop_bot_runtime():
    global _app
    if _app is None:
        return
    try:
        await _app.stop()
    except Exception:
        logger.exception("Error stopping bot")
    try:
        await _app.shutdown()
    except Exception:
        logger.exception("Error shutting down bot")
    _app = None
