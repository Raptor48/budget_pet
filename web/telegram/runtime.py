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


def _webapp_url() -> Optional[str]:
    return (os.getenv("TELEGRAM_WEBAPP_URL") or "").strip() or None


def get_bot_app():
    return _app


async def _register_menu_button(application) -> None:
    """Configure the chat-level Menu button to open our Mini App.

    Inline reply keyboards are capped at the message bubble width and
    can't be made wider on iPhone. The persistent Menu button (bottom-
    left of the chat) opens a full-screen WebApp instead — this is how
    we actually deliver a thumb-friendly main surface. Skipped silently
    when ``TELEGRAM_WEBAPP_URL`` is unset so dev environments don't
    accidentally point users at a stale URL.
    """
    url = _webapp_url()
    if not url:
        # MenuButton was opt-in via TELEGRAM_WEBAPP_URL; we currently do not
        # use the Mini App and want the chat to show the default Commands
        # menu. Resetting on every startup is idempotent and ensures any
        # WebApp button left over from a previous deploy gets cleared.
        try:
            await application.bot.set_chat_menu_button()
            logger.info("Telegram MenuButton reset to default (Commands)")
        except Exception:
            logger.exception("Failed to reset MenuButton to default")
        return
    try:
        from telegram import MenuButtonWebApp, WebAppInfo

        await application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Open app",
                web_app=WebAppInfo(url=url),
            )
        )
        logger.info("Telegram MenuButton set to WebApp at %s", url)
    except Exception:
        # Don't take down bot startup if Telegram is briefly unhappy;
        # the inline /menu fallback still works.
        logger.exception("Failed to register WebApp MenuButton")


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

    await _register_menu_button(application)
    await _register_commands(application)
    return _app


async def _register_commands(application) -> None:
    """Publish the slash-command list shown by the native Menu button.

    The blue "Menu" button next to the input field shows this list when
    tapped. Telegram renders each entry as a wide native row — so we get
    a discoverable, large-tap-target command palette for free, alongside
    the persistent reply keyboard that drives day-to-day navigation.
    """
    try:
        from telegram import BotCommand

        await application.bot.set_my_commands(
            [
                BotCommand("menu", "Open the main menu"),
                BotCommand("balance", "Show today's balance"),
                BotCommand("networth", "Show net worth"),
                BotCommand("upcoming", "Upcoming subscriptions"),
                BotCommand("milestone", "Add a savings milestone"),
                BotCommand("anniversary", "Set anniversary date"),
                BotCommand("link", "Pair this chat with the web app"),
            ]
        )
        logger.info("Telegram bot commands registered")
    except Exception:
        logger.exception("Failed to register bot commands")


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
