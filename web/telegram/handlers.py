"""
Telegram bot handlers — menus, commands, callback queries.

UX rules:
    * One main menu, English-only, six top buttons.
    * Every screen offers a "Back" route. Reach Main with /menu or the back
      stack — never let the user get lost.
    * Callback data is short — ``action[:arg[:arg]]`` — Telegram caps
      callback_data at 64 bytes.
    * Long-form input (anniversary date, milestone amount) uses
      a tiny ``ConversationHandler`` state machine.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from web.bot_api.repo import get_bot_repo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------

LINK_AWAIT_CODE = 1
CASH_AWAIT_AMOUNT = 10
CASH_AWAIT_NOTE = 11
ANNIV_AWAIT_DATE = 20
MILESTONE_AWAIT_AMOUNT = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _money(cents: int, currency: str = "USD") -> str:
    sign = "-" if cents < 0 else ""
    val = abs(cents) / 100.0
    return f"{sign}${val:,.2f}" if currency == "USD" else f"{sign}{val:,.2f} {currency}"


async def _user_for_chat(chat_id: int) -> Optional[Dict[str, Any]]:
    return await get_bot_repo().find_user_by_chat_id(chat_id)


_MENU_PAD_TARGET = 36  # visual width target for every main-menu row


def _pad_label(label: str, target: int = _MENU_PAD_TARGET) -> str:
    """Right-pad ``label`` so the inline keyboard renders at the chat bubble's
    maximum width.

    NBSP renders the same width as a regular space - too narrow to push past
    Telegram's natural keyboard sizing on iOS, so the menu still looked
    compressed. IDEOGRAPHIC SPACE (U+3000) renders roughly twice as wide and
    is preserved (never trimmed) by every Telegram client. Padding every
    single-column button to the same wide target forces the keyboard to
    render at the bubble's max width on every screen, so each row is a
    full-width thumb-friendly tap target regardless of how short the visible
    label is.
    """
    return label + ("　" * max(0, target - len(label)))


def _main_menu_kb() -> InlineKeyboardMarkup:
    # Inline 3x2 grid kept as a fallback surface for users who explicitly
    # type /menu — but the primary main menu now renders as a persistent
    # reply keyboard (see _main_reply_kb) so the buttons are full device
    # width instead of bubble width.
    def _cell(label: str, cb: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(_pad_label(label, target=12), callback_data=cb)

    rows = [
        [
            _cell("➕ Add", "menu:cash"),
            _cell("📊 Today", "menu:today"),
            _cell("🔔 Alerts", "menu:alerts"),
        ],
        [
            _cell("👥 Family", "menu:family"),
            _cell("🎯 Goals", "menu:goals"),
            _cell("⚙️ Settings", "menu:settings"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def _back_kb(target: str = "menu:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data=target)]])


# ---------------------------------------------------------------------------
# Persistent ReplyKeyboard — the primary main-menu surface.
#
# Inline keyboards are bubble-width-bound; on iPhone that caps each button
# at ~75% of screen width even with aggressive ideographic-space padding,
# which is too small for a thumb-first menu. Reply keyboards live in the
# bottom keyboard area instead, so each cell occupies a fraction of the
# *device* width — roughly 2-3x the visible size of an inline button. With
# is_persistent=True the keyboard stays on screen between interactions, so
# the user never has to send /menu again to find their way around.
#
# The trade-off: a tap on a reply-keyboard button sends a normal text
# message containing the button's label. We route those labels back to the
# existing menu handlers via _REPLY_BUTTON_TO_SECTION + an early branch in
# on_text_message so the same submenus light up.
# ---------------------------------------------------------------------------

# Lookup from reply-keyboard label to the menu section it should open.
# Keep the labels here in lock-step with _main_reply_kb below — the
# MessageHandler matches on exact string equality.
_REPLY_BUTTON_TO_SECTION: Dict[str, str] = {
    "➕ Add": "cash",
    "📊 Today": "today",
    "🔔 Alerts": "alerts",
    "👥 Family": "family",
    "🎯 Goals": "goals",
    "⚙️ Settings": "settings",
}


def _main_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("➕ Add"), KeyboardButton("📊 Today")],
            [KeyboardButton("🔔 Alerts"), KeyboardButton("👥 Family")],
            [KeyboardButton("🎯 Goals"), KeyboardButton("⚙️ Settings")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Tap a menu item or type a command",
    )


def _cash_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✏️ Type", callback_data="cash:type"),
                InlineKeyboardButton("📸 Receipt", callback_data="cash:receipt"),
            ],
            [InlineKeyboardButton("🧾 Recent", callback_data="cash:recent")],
            [InlineKeyboardButton("◀️ Back", callback_data="menu:main")],
        ]
    )


def _alerts_menu_kb(prefs: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for p in prefs:
        emoji = "✅" if p["enabled"] else "❌"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{emoji} {p['label']}",
                    callback_data=f"alerts:toggle:{p['alert_type']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("◀️ Back", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def _family_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("☕ Audit", callback_data="family:audit"),
                InlineKeyboardButton("🏆 Top week", callback_data="family:leaderboard"),
            ],
            [
                InlineKeyboardButton("🧹 Chores", callback_data="family:chores"),
                InlineKeyboardButton("💌 Anniversary", callback_data="family:anniv"),
            ],
            [InlineKeyboardButton("◀️ Back", callback_data="menu:main")],
        ]
    )


def _goals_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🎯 Milestones", callback_data="goals:milestones"),
                InlineKeyboardButton("🔥 Streaks", callback_data="goals:streaks"),
            ],
            [InlineKeyboardButton("◀️ Back", callback_data="menu:main")],
        ]
    )


def _settings_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📱 Telegram link", callback_data="settings:link")],
            [InlineKeyboardButton("🌙 Quiet hours", callback_data="settings:quiet")],
            [InlineKeyboardButton("◀️ Back", callback_data="menu:main")],
        ]
    )


# ---------------------------------------------------------------------------
# Auth gate — every command except /start, /link checks if the chat is bound
# ---------------------------------------------------------------------------


async def _ensure_linked(update: Update) -> Optional[Dict[str, Any]]:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        return None
    user = await _user_for_chat(chat_id)
    if not user and update.effective_message:
        await update.effective_message.reply_text(
            "This chat isn't linked yet. Open Budget Pet → <b>Bot</b> page and "
            "tap <i>Generate code</i>, then come back here and send "
            "<code>/link &lt;code&gt;</code>.",
            parse_mode=ParseMode.HTML,
        )
    return user


# ---------------------------------------------------------------------------
# /start — greet + show main menu (or hint to /link)
# ---------------------------------------------------------------------------


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await _user_for_chat(chat_id)
    if user:
        # Anchor the persistent reply keyboard. resize_keyboard + is_persistent
        # together keep the buttons visible at the bottom of every chat in
        # this conversation, so the user never has to type /menu again.
        await update.message.reply_text(
            f"Welcome back, {user['username']} 👋\nPick a section below or"
            " tap a slash-command from the Menu button.",
            reply_markup=_main_reply_kb(),
        )
        return
    await update.message.reply_text(
        "Hi! I'm your Budget Pet assistant.\n\n"
        "Open the web app → <b>Bot</b> page → tap <i>Generate code</i>, then "
        "send <code>/link &lt;code&gt;</code> here so I know who you are.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_linked(update)
    if not user:
        return
    # Re-anchor the reply keyboard. Telegram only renders it after a message
    # is sent that carries the markup, so calling /menu again is a quick
    # way to force it back if the user accidentally hid it.
    await update.message.reply_text(
        "Main menu — buttons stay below.", reply_markup=_main_reply_kb()
    )


# ---------------------------------------------------------------------------
# /link — complete the pairing flow
# ---------------------------------------------------------------------------


async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Send <code>/link CODE</code> where CODE comes from the web app.",
            parse_mode=ParseMode.HTML,
        )
        return
    code = " ".join(context.args).strip().upper()
    repo = get_bot_repo()
    user = await repo.find_user_by_link_code(code)
    if not user:
        await update.message.reply_text("That code isn't valid. Generate a fresh one.")
        return
    expires = user.get("telegram_link_code_expires_at")
    if expires:
        from datetime import timezone as _tz

        if expires.replace(tzinfo=expires.tzinfo or _tz.utc) < datetime.now(_tz.utc):
            await update.message.reply_text("That code expired. Generate a new one.")
            return
    chat = update.effective_chat
    tg_user = update.effective_user
    await repo.attach_telegram_chat(
        user["id"], chat.id, telegram_username=getattr(tg_user, "username", None)
    )
    from web.telegram.activity import log_bot_activity

    await log_bot_activity(
        kind="link.attached",
        summary=f"Linked Telegram chat to user {user['username']}",
        user_id=int(user["id"]),
        chat_id=int(chat.id),
        payload={"telegram_username": getattr(tg_user, "username", None)},
    )
    await update.message.reply_text(
        f"Linked ✅ Welcome, {user['username']}!",
        reply_markup=_main_reply_kb(),
    )


# ---------------------------------------------------------------------------
# Menu drill-downs
# ---------------------------------------------------------------------------


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user = await _user_for_chat(query.message.chat_id)
    if not user:
        await query.edit_message_text(
            "This chat is no longer linked. Re-link from the web app."
        )
        return
    data = query.data or ""
    parts = data.split(":", 3)
    head = parts[0]

    # Activity log — record only "action" callbacks (tea, chore done,
    # receipt action, reauth deep-link). Menu navigation taps are skipped
    # to keep the log readable.
    if head in {"tea", "chore", "receipt", "reauth"}:
        from web.telegram.activity import log_bot_activity

        await log_bot_activity(
            kind="incoming.callback",
            summary=f"Callback: {data}"[:280],
            user_id=int(user["id"]),
            chat_id=int(query.message.chat_id) if query.message else None,
            payload={"data": data},
        )
    if head == "menu":
        await _on_menu(query, user, parts)
    elif head == "alerts":
        await _on_alerts(query, user, parts)
    elif head == "cash":
        await _on_cash(query, user, parts, context)
    elif head == "family":
        await _on_family(query, user, parts)
    elif head == "goals":
        await _on_goals(query, user, parts)
    elif head == "settings":
        await _on_settings(query, user, parts)
    elif head == "tea":
        await _on_tea(query, user, parts)
    elif head == "reauth":
        await _on_reauth(query, user, parts)
    elif head == "chore":
        await _on_chore(query, user, parts)
    elif head == "receipt":
        await _on_receipt_action(query, user, parts)
    elif head == "unsub":
        await _on_unsub(query, user, parts)
    else:
        await query.edit_message_text(
            f"Unknown action: {head}", reply_markup=_back_kb()
        )


async def _on_menu(query, user, parts):
    section = parts[1] if len(parts) > 1 else "main"
    repo = get_bot_repo()
    if section == "main":
        await query.edit_message_text("Main menu:", reply_markup=_main_menu_kb())
    elif section == "cash":
        await query.edit_message_text(
            "➕ <b>Add transaction</b>\nTap <b>Type</b> for a quick entry, "
            "or <b>Receipt</b> to upload a photo.",
            reply_markup=_cash_menu_kb(),
            parse_mode=ParseMode.HTML,
        )
    elif section == "today":
        snapshot = await _today_snapshot(user["id"])
        await query.edit_message_text(
            snapshot, reply_markup=_back_kb(), parse_mode=ParseMode.HTML
        )
    elif section == "alerts":
        prefs = await repo.list_notification_prefs(user["id"])
        await query.edit_message_text(
            "🔔 Toggle alerts (✅ on / ❌ off):", reply_markup=_alerts_menu_kb(prefs)
        )
    elif section == "family":
        await query.edit_message_text("👥 <b>Family</b>", reply_markup=_family_menu_kb(), parse_mode=ParseMode.HTML)
    elif section == "goals":
        await query.edit_message_text("🎯 <b>Goals</b>", reply_markup=_goals_menu_kb(), parse_mode=ParseMode.HTML)
    elif section == "settings":
        await query.edit_message_text("⚙️ <b>Settings</b>", reply_markup=_settings_menu_kb(), parse_mode=ParseMode.HTML)
    else:
        await query.edit_message_text("Main menu:", reply_markup=_main_menu_kb())


async def _on_alerts(query, user, parts):
    repo = get_bot_repo()
    if len(parts) >= 3 and parts[1] == "toggle":
        alert_type = parts[2]
        current = await repo.is_alert_enabled(user["id"], alert_type)
        await repo.set_notification_pref(user["id"], alert_type, not current)
    prefs = await repo.list_notification_prefs(user["id"])
    await query.edit_message_text(
        "🔔 Toggle alerts (✅ on / ❌ off):", reply_markup=_alerts_menu_kb(prefs)
    )


async def _on_cash(query, user, parts, context):
    if len(parts) > 1 and parts[1] == "type":
        context.user_data["cash_state"] = "await_amount"
        await query.edit_message_text(
            "Reply with <code>amount description</code>, e.g. "
            "<code>5 coffee</code> or <code>120 grocery</code>.",
            reply_markup=_back_kb("menu:cash"),
            parse_mode=ParseMode.HTML,
        )
    elif len(parts) > 1 and parts[1] == "receipt":
        context.user_data["cash_state"] = "await_receipt"
        await query.edit_message_text(
            "Send the receipt photo as a regular image (not as a file).",
            reply_markup=_back_kb("menu:cash"),
        )
    elif len(parts) > 1 and parts[1] == "recent":
        rows = await _list_recent_cash(user["id"])
        text = (
            "<b>Recent entries</b>\n\n" + "\n".join(rows)
            if rows
            else "No entries yet."
        )
        await query.edit_message_text(
            text, reply_markup=_back_kb("menu:cash"), parse_mode=ParseMode.HTML
        )
    elif len(parts) > 2 and parts[1] == "undo":
        await _on_cash_undo(query, user, parts)
    elif len(parts) > 2 and parts[1] == "priv":
        await _on_cash_privacy_toggle(query, user, parts)
    else:
        await query.edit_message_text(
            "➕ <b>Add transaction</b>",
            reply_markup=_cash_menu_kb(),
            parse_mode=ParseMode.HTML,
        )


async def _on_cash_undo(query, user, parts):
    """Inline ``↩️ Undo`` after a smart cash entry. Deletes the row + the
    matching wallet adjustment in one transaction (handled by
    ``TransactionsRepository.delete_transaction``). Cap with an ownership
    check so a partner can't undo someone else's entry by guessing the
    callback data."""
    try:
        txn_id = int(parts[2])
    except (ValueError, IndexError):
        await query.answer("Invalid undo target.", show_alert=True)
        return
    from web.transactions.repo import TransactionsRepository

    repo = TransactionsRepository()
    txn = await repo.get_transaction(txn_id)
    if not txn:
        await query.answer("Already gone.", show_alert=True)
        return
    # Ownership: cash transactions live on the user's cash wallet, so the
    # wallet's ``user_id`` should match the linked Telegram user.
    from web.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        owner = await conn.fetchval(
            "SELECT user_id FROM accounts WHERE id = $1",
            int(txn["account_id"]),
        )
    if owner is not None and int(owner) != int(user["id"]):
        await query.answer("Not your transaction.", show_alert=True)
        return
    deleted = await repo.delete_transaction(txn_id)
    if not deleted:
        await query.answer("Could not undo.", show_alert=True)
        return
    try:
        await query.edit_message_text("↩️ Undone.")
    except Exception:
        await query.message.reply_text("↩️ Undone.")


async def _on_cash_privacy_toggle(query, user, parts):
    """Inline ``🔒 Make private`` / ``🔓 Make public`` toggle."""
    try:
        txn_id = int(parts[2])
        target_value = bool(int(parts[3]))
    except (ValueError, IndexError):
        await query.answer("Invalid privacy toggle.", show_alert=True)
        return
    from web.transactions.repo import TransactionsRepository

    repo = TransactionsRepository()
    txn = await repo.get_transaction(txn_id)
    if not txn:
        await query.answer("Transaction not found.", show_alert=True)
        return
    from web.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        owner = await conn.fetchval(
            "SELECT user_id FROM accounts WHERE id = $1",
            int(txn["account_id"]),
        )
    if owner is not None and int(owner) != int(user["id"]):
        await query.answer("Not your transaction.", show_alert=True)
        return
    try:
        await repo.update_transaction(txn_id, {"is_private": target_value})
    except Exception as exc:
        await query.answer(f"Failed: {exc}"[:180], show_alert=True)
        return
    # Flip the inline button label so the next tap reverses the action.
    new_buttons = [
        InlineKeyboardButton("↩️ Undo", callback_data=f"cash:undo:{txn_id}"),
        InlineKeyboardButton(
            "🔓 Make public" if target_value else "🔒 Make private",
            callback_data=f"cash:priv:{txn_id}:{0 if target_value else 1}",
        ),
    ]
    try:
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([new_buttons])
        )
    except Exception:
        pass
    await query.answer("Updated.")


async def _on_family(query, user, parts):
    repo = get_bot_repo()
    sub = parts[1] if len(parts) > 1 else None
    if sub == "audit":
        session = await repo.get_or_create_audit_session()
        host = session.get("host_username") or "—"
        snack = session.get("snack") or "—"
        tea = session.get("tea_choice") or "—"
        notes = session.get("notes") or "—"
        text = (
            f"☕ <b>Audit — week of {session['week_start']}</b>\n\n"
            f"Host: {host}\nSnack: {snack}\nTea: {tea}\nNotes: {notes}"
        )
        await query.edit_message_text(text, reply_markup=_back_kb("menu:family"), parse_mode=ParseMode.HTML)
    elif sub == "leaderboard":
        board = await repo.get_weekly_leaderboard()
        if not board["entries"]:
            await query.edit_message_text(
                "No data this week yet. Sync first.",
                reply_markup=_back_kb("menu:family"),
            )
            return
        lines = ["🏆 <b>Top of the week</b>"]
        for e in board["entries"][:8]:
            lines.append(
                f"• {e['username']} — {e['category_name']} "
                f"{_money(int(e['amount_cents']))}"
            )
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=_back_kb("menu:family"),
            parse_mode=ParseMode.HTML,
        )
    elif sub == "chores":
        await _render_chores(query, user)
    elif sub == "anniv":
        settings = await repo.get_couple_settings(user["id"])
        d = settings.get("anniversary_date")
        text = (
            f"💌 Your anniversary: <b>{d.strftime('%B %d, %Y')}</b>"
            if d
            else "No anniversary set yet. Use /anniversary to set it."
        )
        await query.edit_message_text(text, reply_markup=_back_kb("menu:family"), parse_mode=ParseMode.HTML)
    else:
        await query.edit_message_text(
            "👥 <b>Family</b>",
            reply_markup=_family_menu_kb(),
            parse_mode=ParseMode.HTML,
        )


async def _on_goals(query, user, parts):
    repo = get_bot_repo()
    sub = parts[1] if len(parts) > 1 else None
    if sub == "milestones":
        rows = await repo.list_milestones(user["id"])
        if not rows:
            text = "No milestones yet. Use <code>/milestone &lt;amount&gt;</code> to add one."
        else:
            lines = ["🎯 <b>Net-worth milestones</b>"]
            for r in rows:
                badge = "✅" if r["reached_at"] else "•"
                lines.append(f"{badge} {_money(r['threshold_cents'])} {r.get('label') or ''}".strip())
            text = "\n".join(lines)
        await query.edit_message_text(
            text, reply_markup=_back_kb("menu:goals"), parse_mode=ParseMode.HTML
        )
    elif sub == "streaks":
        streaks = await repo.list_streaks(user["id"])
        active = [s for s in streaks if s["current_count"] > 0]
        if not active:
            text = "No active streaks yet — start by syncing weekly 🔥"
        else:
            lines = ["🔥 <b>Streaks</b>"]
            for s in active:
                lines.append(f"• {s['label']} — {s['current_count']} (best {s['longest_count']})")
            text = "\n".join(lines)
        await query.edit_message_text(
            text, reply_markup=_back_kb("menu:goals"), parse_mode=ParseMode.HTML
        )
    else:
        await query.edit_message_text("🎯 <b>Goals</b>", reply_markup=_goals_menu_kb(), parse_mode=ParseMode.HTML)


async def _on_settings(query, user, parts):
    sub = parts[1] if len(parts) > 1 else None
    repo = get_bot_repo()
    if sub == "link":
        status = await repo.get_telegram_link_status(user["id"])
        text = (
            f"📱 Linked as <b>{status.get('telegram_username') or '—'}</b>\n"
            f"Chat id: <code>{status.get('chat_id')}</code>"
        )
        await query.edit_message_text(text, reply_markup=_back_kb("menu:settings"), parse_mode=ParseMode.HTML)
    elif sub == "quiet":
        cs = await repo.get_couple_settings(user["id"])
        text = (
            f"🌙 Quiet hours: <b>{cs['quiet_hours_start'].strftime('%H:%M')}"
            f" – {cs['quiet_hours_end'].strftime('%H:%M')}</b>\n"
            f"Morning brief: <b>{cs['morning_brief_local'].strftime('%H:%M')}</b> "
            f"({cs['morning_brief_tz']})\n\n"
            "Change these from the web app → <b>Bot</b> page → Settings."
        )
        await query.edit_message_text(
            text, reply_markup=_back_kb("menu:settings"), parse_mode=ParseMode.HTML
        )
    else:
        await query.edit_message_text(
            "⚙️ <b>Settings</b>",
            reply_markup=_settings_menu_kb(),
            parse_mode=ParseMode.HTML,
        )


async def _on_tea(query, user, parts):
    choice = parts[1] if len(parts) > 1 else None
    if choice == "skip":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text("Maybe next week ✨")
        return
    label = {"earl_grey": "Earl Grey", "sencha": "Sencha"}.get(choice, choice or "Tea")
    await get_bot_repo().update_audit_session(date.today(), {"tea_choice": label})
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await query.message.reply_text(f"☕ {label} it is.")


async def _on_unsub(query, user, parts):
    """Handle the two inline buttons on the "unsubscribe charge detected" P0:

      * ``unsub:reactivate:<stream_id>`` — user changed their mind; move
        the stream back to ``active``.
      * ``unsub:cancel:<stream_id>`` — user wants to force-confirm; move
        the stream to ``cancelled``.

    Ownership is enforced by joining ``accounts.user_id`` against the
    Telegram-linked user: a partner can't accept an alert addressed to
    the other partner's account from their own chat. Shared accounts
    (``accounts.user_id IS NULL``) are accepted from any household
    member — that mirrors how the recurring page itself is family-wide.
    """
    if len(parts) < 3:
        await query.edit_message_text("Malformed action.")
        return
    action = parts[1]
    try:
        stream_id = int(parts[2])
    except (TypeError, ValueError):
        await query.edit_message_text("Malformed stream id.")
        return
    if action not in ("reactivate", "cancel"):
        await query.edit_message_text("Unknown action.")
        return

    from web.db import get_pool
    from web.recurring.repo import RecurringRepository

    pool = await get_pool()
    async with pool.acquire() as conn:
        owner_row = await conn.fetchrow(
            """
            SELECT a.user_id AS owner_user_id, rs.merchant_name, rs.description
            FROM recurring_streams rs
            LEFT JOIN accounts a ON a.id = rs.account_id
            WHERE rs.id = $1
            """,
            stream_id,
        )
    if owner_row is None:
        await query.edit_message_text("This stream no longer exists.")
        return
    owner_uid = owner_row["owner_user_id"]
    if owner_uid is not None and int(owner_uid) != int(user["id"]):
        await query.edit_message_text("This alert was sent to another household member.")
        return

    new_status = "active" if action == "reactivate" else "cancelled"
    repo = RecurringRepository()
    updated = await repo.update_stream(stream_id, {"user_status": new_status})
    if updated is None:
        await query.edit_message_text("Couldn't update the stream — try again from the app.")
        return

    label = (
        owner_row.get("merchant_name")
        or owner_row.get("description")
        or "Subscription"
    )
    if new_status == "active":
        body = f"✅ <b>{label}</b> reactivated — back to your forecast."
    else:
        body = f"🚫 <b>{label}</b> marked as cancelled."
    await query.edit_message_text(body, parse_mode=ParseMode.HTML)


async def _on_reauth(query, user, parts):
    item_id = parts[1] if len(parts) > 1 else ""
    base = (await _frontend_base_url())
    url = f"{base}/settings#bank-{item_id}" if item_id else f"{base}/settings"
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        f"Open {url} to re-link the bank.", disable_web_page_preview=False
    )


# ---------------------------------------------------------------------------
# Chores — Family → 🧹 view, plus the "Mark done" callback
# ---------------------------------------------------------------------------


async def _render_chores(query, user) -> None:
    """Show every chore assigned this week. Status icon for everyone (so the
    audit ritual is fully transparent across both partners) but the
    [Mark done] inline button only shows for chores assigned to the
    current user."""
    repo = get_bot_repo()
    week = _bot_week_start_iso()
    members = await _household_user_ids()
    assignments = await repo.regenerate_week_assignments(
        date.fromisoformat(week), members
    )
    assignments = await repo.list_assignments_for_week(date.fromisoformat(week))

    if not assignments:
        await query.edit_message_text(
            "🧹 No chores configured yet — open the web app → Bot → Chores to set them up.",
            reply_markup=_back_kb("menu:family"),
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [f"🧹 <b>Chores — week of {week}</b>", ""]
    rows: List[List[InlineKeyboardButton]] = []
    for a in assignments:
        icon = a.get("chore_icon") or "🧹"
        done = a.get("completed_at") is not None
        marker = "✅" if done else "🔘"
        owner = a.get("username") or "?"
        lines.append(
            f"{marker} {icon} <b>{a['chore_name']}</b> — {owner}"
            + (" <i>(done)</i>" if done else "")
        )
        if not done and int(a["user_id"]) == int(user["id"]):
            rows.append(
                [
                    InlineKeyboardButton(
                        f"Mark done · {a['chore_name']}",
                        callback_data=f"chore:done:{a['chore_id']}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton("◀️ Back", callback_data="menu:family")])
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.HTML,
    )


async def _on_chore(query, user, parts) -> None:
    if len(parts) < 3 or parts[1] != "done":
        return
    try:
        chore_id = int(parts[2])
    except ValueError:
        return
    repo = get_bot_repo()
    week = date.fromisoformat(_bot_week_start_iso())
    assignments = await repo.list_assignments_for_week(week)
    target = next((a for a in assignments if int(a["chore_id"]) == chore_id), None)
    if not target:
        await query.answer("Chore not found this week.", show_alert=True)
        return
    if int(target["user_id"]) != int(user["id"]):
        await query.answer("That one's not on your plate.", show_alert=True)
        return
    await repo.set_assignment_completed(chore_id, week, True)
    # Re-render the whole list so the user sees the status flip in place.
    await _render_chores(query, user)


def _bot_week_start_iso() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


async def _household_user_ids() -> List[int]:
    """All users in the household — chore rotation rotates over this list."""
    from web.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM users ORDER BY id")
    return [int(r["id"]) for r in rows]


# ---------------------------------------------------------------------------
# /balance, /networth, /upcoming — quick read-only commands
# ---------------------------------------------------------------------------


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_linked(update)
    if not user:
        return
    text = await _today_snapshot(user["id"])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_networth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_linked(update)
    if not user:
        return
    nw = await _latest_networth()
    if nw is None:
        await update.message.reply_text(
            "Net worth not yet computed. Run a Plaid sync first."
        )
        return
    await update.message.reply_text(
        f"📈 <b>Net worth: {_money(nw)}</b>\n"
        f"<i>Total assets minus all debts. Updated after the last sync.</i>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_linked(update)
    if not user:
        return
    rows = await _upcoming_recurring(days=14)
    if not rows:
        await update.message.reply_text("Nothing recurring in the next 14 days.")
        return
    lines = ["📅 <b>Next 14 days</b>"]
    for r in rows[:15]:
        date_str = r["next_date"].strftime("%b %d")
        lines.append(
            f"• {date_str} — {r['name']} {_money(int(r['amount_cents']))}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# Cash quick-entry — text "AMT description" → cash transaction
# ---------------------------------------------------------------------------


async def _open_main_section(
    update: Update, user: Dict[str, Any], section: str
) -> None:
    """Render a top-level menu section as a NEW message (no callback query).

    This is the reply-keyboard counterpart of ``_on_menu``: when the user
    taps "➕ Add" / "📊 Today" / etc. on the persistent reply keyboard, the
    bot receives a plain text message and we open the corresponding submenu
    by sending a fresh message. We keep ``_on_menu`` unchanged because it's
    still used for inline callback navigation (back buttons, drill-downs).
    """
    repo = get_bot_repo()
    msg = update.message
    if section == "cash":
        await msg.reply_text(
            "➕ <b>Add transaction</b>\nTap <b>Type</b> for a quick entry, "
            "or <b>Receipt</b> to upload a photo.",
            reply_markup=_cash_menu_kb(),
            parse_mode=ParseMode.HTML,
        )
    elif section == "today":
        snapshot = await _today_snapshot(user["id"])
        await msg.reply_text(
            snapshot, reply_markup=_back_kb(), parse_mode=ParseMode.HTML
        )
    elif section == "alerts":
        prefs = await repo.list_notification_prefs(user["id"])
        await msg.reply_text(
            "🔔 Toggle alerts (✅ on / ❌ off):", reply_markup=_alerts_menu_kb(prefs)
        )
    elif section == "family":
        await msg.reply_text(
            "👥 <b>Family</b>",
            reply_markup=_family_menu_kb(),
            parse_mode=ParseMode.HTML,
        )
    elif section == "goals":
        await msg.reply_text(
            "🎯 <b>Goals</b>",
            reply_markup=_goals_menu_kb(),
            parse_mode=ParseMode.HTML,
        )
    elif section == "settings":
        await msg.reply_text(
            "⚙️ <b>Settings</b>",
            reply_markup=_settings_menu_kb(),
            parse_mode=ParseMode.HTML,
        )


async def on_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from web.telegram.activity import log_bot_activity

    user = await _ensure_linked(update)
    if not user:
        return
    chat_id = update.effective_chat.id if update.effective_chat else None
    txt = (update.message.text or "").strip()
    if not txt:
        return

    # Persistent reply-keyboard taps arrive here as plain text. Dispatch to
    # the matching menu section before trying to parse the message as a
    # cash entry. Skipped while a conversation handler is mid-flight (e.g.
    # the cash-entry "await amount" state) so keystroke flow isn't hijacked.
    if (
        txt in _REPLY_BUTTON_TO_SECTION
        and not context.user_data.get("cash_state")
    ):
        await log_bot_activity(
            kind="incoming.text",
            summary=f"Reply-keyboard tap: {txt}",
            user_id=user["id"],
            chat_id=chat_id,
            payload={"section": _REPLY_BUTTON_TO_SECTION[txt]},
        )
        await _open_main_section(update, user, _REPLY_BUTTON_TO_SECTION[txt])
        return

    parsed = await _parse_cash_entry_smart(user["id"], txt)
    if parsed is None:
        await update.message.reply_text(
            "Try <code>5 coffee</code> or <code>120 grocery</code>.",
            parse_mode=ParseMode.HTML,
        )
        return
    amount_cents, name, meta = parsed
    is_private = bool(meta.get("is_private"))
    try:
        result = await _post_cash_transaction(
            user, amount_cents, name, is_private=is_private
        )
    except RuntimeError as exc:
        await log_bot_activity(
            kind="incoming.text",
            severity="warn",
            summary=f"Cash entry rejected: {exc}",
            user_id=user["id"],
            chat_id=chat_id,
            payload={"raw": txt[:200]},
        )
        await update.message.reply_text(str(exc))
        return
    await log_bot_activity(
        kind="incoming.text",
        summary=f"Cash entry: {name} · {_money(amount_cents)}{' (LLM)' if meta.get('source') == 'llm' else ''}",
        user_id=user["id"],
        chat_id=chat_id,
        payload={
            "transaction_id": int(result["id"]),
            "amount_cents": amount_cents,
            "parser": meta.get("source", "deterministic"),
            "is_private": is_private,
        },
    )
    # Inline confirm — single tap to undo or flip privacy. Edit-category
    # is intentionally absent here; the FE has a richer category picker
    # and we don't want a callback_data race against the fast-tap user.
    txn_id = int(result["id"])
    buttons = [
        InlineKeyboardButton("↩️ Undo", callback_data=f"cash:undo:{txn_id}"),
    ]
    # Toggle reflects the *new* state we'd apply on tap, so the label is
    # the intent, not the current value.
    buttons.append(
        InlineKeyboardButton(
            "🔓 Make public" if is_private else "🔒 Make private",
            callback_data=f"cash:priv:{txn_id}:{0 if is_private else 1}",
        )
    )
    keyboard = InlineKeyboardMarkup([buttons])
    suffix = " 🔒" if is_private else ""
    smart_hint = (
        " <i>(smart parse)</i>"
        if meta.get("source") == "llm"
        else ""
    )
    await update.message.reply_text(
        f"💸 Logged <b>{result['name']}</b> {_money(amount_cents)}{suffix}{smart_hint}",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def _parse_cash_entry_smart(
    user_id: int, text: str
) -> Optional[Tuple[int, str, Dict[str, Any]]]:
    """Two-stage parse: deterministic first, LLM fallback when the
    deterministic parser couldn't extract an amount AND the per-user
    daily quota is not exhausted.

    Returns ``(amount_cents, name, meta)`` where ``meta`` carries
    ``source`` (``"deterministic"`` | ``"llm"``) and any structured hints
    the caller wants — currently ``is_private``.
    """
    from web.telegram import cash_parser

    deterministic = cash_parser.parse_deterministic(text)
    if deterministic is not None:
        amount, name = deterministic
        return amount, name, {"source": "deterministic", "is_private": False}

    if not cash_parser.llm_enabled():
        return None
    try:
        remaining = await cash_parser.llm_quota_remaining(user_id)
    except Exception:
        # If we can't read the quota table (early boot, DB blip), skip
        # the LLM path rather than risk uncapped spend.
        logger.exception("Could not read LLM quota for user=%s", user_id)
        return None
    if remaining <= 0:
        logger.info("LLM cash-entry quota exhausted for user=%s", user_id)
        return None

    llm_result = await cash_parser.parse_with_llm(text)
    if llm_result is None:
        return None
    try:
        await cash_parser.record_llm_call(user_id)
    except Exception:
        # Recording is best-effort. A miss means a user could squeeze one
        # extra call past the cap on a quota-edge race; not worth failing
        # the actual cash entry over.
        logger.exception(
            "Could not record LLM quota usage for user=%s", user_id
        )
    return (
        int(llm_result["amount_cents"]),
        llm_result["name"],
        {
            "source": "llm",
            "is_private": llm_result.get("is_private", False),
            "currency": llm_result.get("currency"),
        },
    )


# ---------------------------------------------------------------------------
# Receipt photo → OCR → cash transaction (no split for MVP)
# ---------------------------------------------------------------------------


async def on_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receipts arrive unlinked.

    Auto-syncing happens weekly, so we can't reliably auto-match a fresh
    receipt photo to a Plaid-imported transaction (it might not exist yet).
    Instead we store the photo + parsed lines + total, leave
    ``transaction_id = NULL`` and offer two follow-ups:

    * **Log as cash** — for receipts paid in cash; creates a manual cash
      transaction in the user's wallet and links the receipt to it.
    * **Wait for sync** — the receipt sits in /bot → Receipts where the
      user can manually attach it to any imported transaction once Plaid
      pulls it in.

    The Insights feed nags the user 7 days later if a receipt is still
    unlinked.
    """
    from web.telegram.activity import log_bot_activity

    user = await _ensure_linked(update)
    if not user:
        return
    chat_id = update.effective_chat.id if update.effective_chat else None
    await log_bot_activity(
        kind="incoming.photo",
        summary="Receipt photo received",
        user_id=user["id"],
        chat_id=chat_id,
    )
    photo = update.message.photo[-1]  # largest
    file = await context.bot.get_file(photo.file_id)
    # PTB's download_to_memory writes via .write(), so a file-like buffer
    # is required. A plain bytearray has no .write attribute and crashed
    # the handler with AttributeError before this fix.
    import io as _io

    bio = _io.BytesIO()
    await file.download_to_memory(out=bio)
    raw_bytes = bio.getvalue()

    # Resize + JPEG-recompress before storage AND before OCR. iPhone shots
    # are 3-4 MB at 3024×4032; trimming to 1600 px max edge produces
    # ~350 KB with no OCR-relevant quality loss (gpt-4o-mini tiles at
    # 512 px). Smaller bytes = smaller Postgres footprint, faster OpenAI
    # upload, and EXIF (GPS!) gets stripped as a privacy bonus.
    from web.telegram.image_processing import normalise_receipt_image

    image_bytes, image_mime = await asyncio.to_thread(
        normalise_receipt_image, raw_bytes
    )

    await update.message.reply_text("📸 Scanning receipt…")
    try:
        from web.telegram.ocr import extract_receipt

        parsed = await extract_receipt(image_bytes)
    except Exception as exc:
        logger.exception("OCR failed")
        await log_bot_activity(
            kind="ocr.failure",
            severity="error",
            summary=f"OCR failed: {exc}"[:280],
            user_id=user["id"],
            chat_id=chat_id,
            error=exc,
        )
        await update.message.reply_text(f"OCR failed: {exc}")
        return
    if not parsed or not parsed.get("total_cents"):
        await log_bot_activity(
            kind="ocr.failure",
            severity="warn",
            summary="OCR returned no total",
            user_id=user["id"],
            chat_id=chat_id,
            payload={"parsed": parsed},
        )
        await update.message.reply_text(
            "Couldn't read a total off this receipt. Try a clearer photo."
        )
        return

    name = parsed.get("merchant_name") or "Receipt"
    total_cents = int(parsed["total_cents"])

    receipt = await get_bot_repo().create_receipt(
        user_id=user["id"],
        image_data=image_bytes,
        image_mime=image_mime,
        merchant_name=parsed.get("merchant_name"),
        receipt_date=parsed.get("date"),
        total_cents=total_cents,
        tax_cents=parsed.get("tax_cents"),
        currency=parsed.get("currency") or "USD",
        raw_ocr_json=parsed,
        lines=parsed.get("lines"),
    )
    await log_bot_activity(
        kind="ocr.success",
        summary=f"OCR parsed: {name} · {_money(total_cents)}",
        user_id=user["id"],
        chat_id=chat_id,
        payload={
            "receipt_id": receipt["id"],
            "merchant": parsed.get("merchant_name"),
            "total_cents": total_cents,
            "line_count": len(parsed.get("lines") or []),
        },
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💵 Log as cash",
                    callback_data=f"receipt:cash:{receipt['id']}",
                ),
                InlineKeyboardButton(
                    "🕒 Wait for sync",
                    callback_data=f"receipt:wait:{receipt['id']}",
                ),
            ]
        ]
    )
    await update.message.reply_text(
        f"📸 Captured <b>{name}</b> · {_money(total_cents)}\n"
        f"<i>Saved unlinked. Either log it as a cash spend now, or leave it "
        f"and attach to a synced bank transaction later from the web app "
        f"(<b>Bot → Receipts</b>).</i>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def _on_receipt_action(query, user, parts) -> None:
    """Handle the [Log as cash] / [Wait for sync] follow-up buttons."""
    if len(parts) < 3:
        return
    action = parts[1]
    try:
        receipt_id = int(parts[2])
    except ValueError:
        return
    repo = get_bot_repo()
    receipt = await repo.get_receipt(user["id"], receipt_id)
    if not receipt:
        await query.answer("Receipt not found.", show_alert=True)
        return
    if action == "wait":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            "🕒 Saved. Attach it later from the web app → Bot → Receipts.",
        )
        return
    if action == "cash":
        if receipt.get("transaction_id"):
            await query.answer("Already linked.", show_alert=True)
            return
        amount_cents = int(receipt.get("total_cents") or 0)
        if amount_cents <= 0:
            await query.answer("This receipt has no total.", show_alert=True)
            return
        name = receipt.get("merchant_name") or "Receipt"
        try:
            txn = await _post_cash_transaction(
                user,
                amount_cents,
                name,
                receipt_merchant=receipt.get("merchant_name"),
                receipt_date=receipt.get("receipt_date"),
            )
        except RuntimeError as exc:
            await query.answer(str(exc), show_alert=True)
            return
        # Effective atomicity for the (cash insert) + (receipt link) pair.
        # The two writes hit different connections so a true BEGIN/COMMIT
        # isn't possible without restructuring the repos. If the link
        # fails, roll back the cash row by hand so we don't leave an
        # orphan in the wallet (cash logged but receipt unlinked is the
        # exact "money double-counted" pattern documented in
        # ``link_receipt(delete_linked_cash=True)``).
        try:
            await repo.attach_receipt_to_transaction(receipt_id, int(txn["id"]))
        except Exception as exc:
            from web.transactions.repo import TransactionsRepository

            logger.exception(
                "attach_receipt_to_transaction failed; rolling back cash txn=%s",
                txn["id"],
            )
            try:
                await TransactionsRepository().delete_transaction(int(txn["id"]))
            except Exception:
                logger.exception(
                    "Failed to roll back orphan cash txn=%s", txn["id"]
                )
            await query.answer(
                f"Could not link receipt: {exc}"[:180], show_alert=True
            )
            return
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            f"💵 Logged <b>{name}</b> {_money(amount_cents)} as cash.",
            parse_mode=ParseMode.HTML,
        )


# ---------------------------------------------------------------------------
# /anniversary, /milestone — one-shot conversation handlers
# ---------------------------------------------------------------------------


async def cmd_anniversary_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_linked(update)
    if not user:
        return ConversationHandler.END
    context.user_data["anniv_user_id"] = user["id"]
    await update.message.reply_text(
        "When is your anniversary? Send the date as <code>DD.MM.YYYY</code> "
        "(e.g. <code>12.06.2019</code>) or <code>DD.MM</code> for the year you wed.",
        parse_mode=ParseMode.HTML,
    )
    return ANNIV_AWAIT_DATE


async def cmd_anniversary_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    parsed = _parse_date(txt)
    if parsed is None:
        await update.message.reply_text(
            "I can't parse that. Try <code>DD.MM.YYYY</code> or /cancel.",
            parse_mode=ParseMode.HTML,
        )
        return ANNIV_AWAIT_DATE
    user_id = context.user_data.get("anniv_user_id")
    await get_bot_repo().update_couple_settings(
        int(user_id), {"anniversary_date": parsed}
    )
    await update.message.reply_text(
        f"💌 Saved <b>{parsed.strftime('%B %d, %Y')}</b>.",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def cmd_milestone_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_linked(update)
    if not user:
        return ConversationHandler.END
    context.user_data["milestone_user_id"] = user["id"]
    await update.message.reply_text(
        "Send the milestone amount in dollars (e.g. <code>100000</code>) and "
        "an optional label after a comma: <code>250000, dream apartment</code>.",
        parse_mode=ParseMode.HTML,
    )
    return MILESTONE_AWAIT_AMOUNT


async def cmd_milestone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    label: Optional[str] = None
    if "," in txt:
        amount_part, label_part = txt.split(",", 1)
        label = label_part.strip() or None
        txt = amount_part.strip()
    txt = txt.replace("$", "").replace(",", "").strip()
    try:
        cents = int(round(float(txt) * 100))
    except ValueError:
        await update.message.reply_text("Couldn't parse the amount. Try again or /cancel.")
        return MILESTONE_AWAIT_AMOUNT
    if cents <= 0:
        await update.message.reply_text("Amount must be positive.")
        return MILESTONE_AWAIT_AMOUNT
    user_id = int(context.user_data.get("milestone_user_id"))
    await get_bot_repo().add_milestone(user_id, cents, label)
    await update.message.reply_text(
        f"🎯 Added milestone {_money(cents)}{' — ' + label if label else ''}."
    )
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Internal helpers — wire the bot to existing repositories
# ---------------------------------------------------------------------------


def _parse_cash_entry(text: str) -> Optional[Tuple[int, str]]:
    """Compatibility shim — delegates to the new deterministic parser in
    :mod:`web.telegram.cash_parser`. The hot path now goes through
    :func:`_parse_cash_entry_smart` which adds an optional LLM fallback;
    callers that just want the regex pass keep using this name."""
    from web.telegram.cash_parser import parse_deterministic

    return parse_deterministic(text)


def _parse_date(s: str) -> Optional[date]:
    s = s.strip()
    formats = ["%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m"]
    for fmt in formats:
        try:
            d = datetime.strptime(s, fmt).date()
            if "%Y" not in fmt:
                d = d.replace(year=date.today().year)
            return d
        except ValueError:
            continue
    return None


# Plaid account types — `type` is the broad bucket ('depository', 'credit',
# 'loan', 'investment', 'other'). Liability buckets carry positive balances
# that represent DEBT, so summing them with assets would be nonsense.
_LIABILITY_TYPES = ("credit", "loan")


async def _today_snapshot(user_id: int) -> str:
    """Render the Today/balance card with proper assets vs liabilities split.

    The previous version SUM()ed every account's current_balance, which
    treated credit-card debt as a positive asset — confusing the headline
    number relative to /networth (which uses the canonical
    net_worth_snapshots calculation, assets − liabilities).
    """
    from web.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT type,
                   subtype,
                   COALESCE(SUM(current_balance_cents), 0) AS total,
                   COUNT(*) AS n
            FROM accounts
            WHERE is_active = TRUE
            GROUP BY type, subtype
            """,
        )
        nw = await conn.fetchval(
            "SELECT net_worth_cents FROM net_worth_snapshots ORDER BY snapshot_date DESC LIMIT 1"
        )

    cash_cents = 0
    savings_cents = 0
    investments_cents = 0
    credit_cents = 0
    loan_cents = 0
    n_total = 0
    for r in rows:
        n_total += int(r["n"])
        amount = int(r["total"])
        atype = (r["type"] or "").lower()
        subtype = (r["subtype"] or "").lower()
        if atype == "credit":
            credit_cents += amount
        elif atype == "loan":
            loan_cents += amount
        elif atype == "investment":
            investments_cents += amount
        elif atype == "depository":
            if subtype == "savings":
                savings_cents += amount
            else:
                cash_cents += amount
        else:
            cash_cents += amount  # "other" / cash wallets fall here

    assets = cash_cents + savings_cents + investments_cents
    liabilities = credit_cents + loan_cents
    net_worth = (
        int(nw)
        if nw is not None
        else assets - liabilities  # fallback if a snapshot hasn't run yet
    )

    lines = [f"📊 <b>Today</b> — {n_total} accounts", ""]
    lines.append("<b>Assets</b>")
    if cash_cents:
        lines.append(f"💵 Cash & checking   {_money(cash_cents)}")
    if savings_cents:
        lines.append(f"🏦 Savings           {_money(savings_cents)}")
    if investments_cents:
        lines.append(f"📈 Investments       {_money(investments_cents)}")
    if not (cash_cents or savings_cents or investments_cents):
        lines.append("—")
    if liabilities:
        lines.append("")
        lines.append("<b>Liabilities</b>")
        if credit_cents:
            lines.append(f"💳 Credit cards      {_money(-credit_cents)}")
        if loan_cents:
            lines.append(f"🏠 Loans             {_money(-loan_cents)}")
    lines.append("")
    lines.append(f"<b>Net worth</b>        {_money(net_worth)}")
    lines.append("")
    lines.append("<i>Net worth = assets − debts. Use /upcoming for charges due soon.</i>")
    return "\n".join(lines)


async def _list_recent_cash(user_id: int) -> List[str]:
    from web.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.date, COALESCE(t.display_title, t.name) AS name, t.amount_cents
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE t.source = 'manual' AND a.plaid_account_id IS NULL
            ORDER BY t.date DESC, t.id DESC
            LIMIT 10
            """,
        )
    return [
        f"• {r['date']} — {r['name']} {_money(int(r['amount_cents']))}" for r in rows
    ]


async def _latest_networth() -> Optional[int]:
    from web.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT net_worth_cents FROM net_worth_snapshots ORDER BY snapshot_date DESC LIMIT 1"
        )
    return int(row["net_worth_cents"]) if row else None


_RECURRING_DESC_NOISE_RE = re.compile(
    # Plaid descriptions trail with junk like "ST-V6A8O8X8 WEB ID:1800948598",
    # "CCD ID: 2462467002", purchase city/state strings, raw account masks.
    # Trim from the first occurrence — leaves the human-readable lead intact.
    r"\s+(?:CARD\s*\d+|WEB\s*ID:.*|CCD\s*ID:?\s*\d+|ID:?\s*\d{6,}|"
    r"ST-[A-Z0-9]+|PPD\s*ID:?\s*\d+|TEL\s*ID:?\s*\d+).*$",
    flags=re.IGNORECASE,
)


def _clean_recurring_label(
    *, user_label: Optional[str], merchant_name: Optional[str], description: Optional[str]
) -> str:
    """user_label > merchant_name > clean(description) — same precedence as the
    web app's recurring page (see `web/insights/cards.py:_stream_label`)."""
    if user_label and user_label.strip():
        return user_label.strip()
    if merchant_name and merchant_name.strip():
        return merchant_name.strip()
    raw = (description or "").strip()
    if not raw:
        return "Subscription"
    cleaned = _RECURRING_DESC_NOISE_RE.sub("", raw).strip()
    # Title-case only if the source was ALL CAPS — preserve mixed-case names.
    if cleaned and cleaned == cleaned.upper():
        cleaned = cleaned.title()
    return cleaned or "Subscription"


async def _upcoming_recurring(days: int = 14) -> List[Dict[str, Any]]:
    from web.db import get_pool

    pool = await get_pool()
    target = date.today() + timedelta(days=days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_label, merchant_name, description,
                   average_amount_cents AS amount_cents,
                   (last_date + INTERVAL '1 month')::date AS next_date
            FROM recurring_streams
            WHERE is_active = TRUE
              AND user_status = 'active'
              AND last_date IS NOT NULL
              AND last_date >= NOW() - INTERVAL '60 days'
            """,
        )
    out: List[Dict[str, Any]] = []
    for r in rows:
        nd = r["next_date"]
        if nd is None or nd > target:
            continue
        out.append(
            {
                "name": _clean_recurring_label(
                    user_label=r["user_label"],
                    merchant_name=r["merchant_name"],
                    description=r["description"],
                ),
                "amount_cents": r["amount_cents"] or 0,
                "next_date": nd,
            }
        )
    out.sort(key=lambda x: x["next_date"])
    return out


async def _frontend_base_url() -> str:
    import os

    base = os.getenv("PUBLIC_FRONTEND_URL") or os.getenv("CORS_ORIGINS") or ""
    if "," in base:
        base = base.split(",")[0]
    return (base or "https://example.com").strip().rstrip("/")


async def _post_cash_transaction(
    user: Dict[str, Any],
    amount_cents: int,
    name: str,
    *,
    receipt_merchant: Optional[str] = None,
    receipt_date: Optional[date] = None,
    is_private: bool = False,
) -> Dict[str, Any]:
    """Insert a manual cash transaction. Picks the user's primary cash wallet
    (by account.user_id if set, else the first non-Plaid account).

    Receipt rows are now stored independently via
    :meth:`BotRepository.create_receipt`; the photo handler links them to a
    transaction explicitly via ``attach_receipt_to_transaction`` so the user
    can choose between cash flow and waiting for a Plaid match.

    ``is_private=True`` flags the row hidden in family-wide aggregates
    (Income/Expenses tab, Cash Flow). The flag still respects the privacy
    rule that the row remains visible to its owner. Used by the smart
    cash-entry path when the LLM detects a "приват" / "private" hint
    in the user's text — and by the inline ``cash:priv`` toggle.
    """
    from web.db import get_pool
    from web.transactions.repo import TransactionsRepository

    pool = await get_pool()
    async with pool.acquire() as conn:
        wallet = await conn.fetchrow(
            """
            SELECT id FROM accounts
            WHERE plaid_account_id IS NULL
              AND is_active = TRUE
              AND (user_id = $1 OR user_id IS NULL)
            ORDER BY (user_id = $1) DESC, id
            LIMIT 1
            """,
            user["id"],
        )
    if not wallet:
        raise RuntimeError(
            "No cash wallet found. Create one in the web app first."
        )
    repo = TransactionsRepository()
    payload: Dict[str, Any] = {
        "account_id": wallet["id"],
        "amount_cents": amount_cents,
        "currency": "USD",
        "date": receipt_date or date.today(),
        "name": name,
        "merchant_name": receipt_merchant,
        "source": "manual",
    }
    row = await repo.create_cash_transaction(payload)
    # ``create_cash_transaction`` doesn't accept ``is_private`` directly —
    # the column lives on the row but the INSERT clause is fixed. Patch it
    # post-create with a single UPDATE so the smart-parser path can
    # honour an "I want this private" hint without reshaping the repo.
    if is_private:
        try:
            updated = await repo.update_transaction(
                int(row["id"]), {"is_private": True}
            )
            if updated:
                row = updated
        except Exception:
            logger.exception(
                "Failed to flip is_private on new cash txn=%s", row["id"]
            )
    return row


# ---------------------------------------------------------------------------
# Wire-up
# ---------------------------------------------------------------------------


async def _on_error(update, context: ContextTypes.DEFAULT_TYPE):
    """Global handler — log the exception and tell the user something broke.

    Without this, PTB swallows handler exceptions into a single warning line
    in the logs and the user sees nothing — UX-fatal for bot menus where
    every tap is a separate update.
    """
    logger.exception("Bot handler crashed", exc_info=context.error)
    chat = getattr(update, "effective_chat", None)
    chat_id = chat.id if chat is not None else None

    # Best-effort linked user lookup so the error shows up scoped to the
    # right user_id in the Activity tab.
    user_id = None
    if chat_id is not None:
        try:
            linked = await get_bot_repo().find_user_by_chat_id(chat_id)
            if linked:
                user_id = int(linked["id"])
        except Exception:
            pass

    from web.telegram.activity import log_bot_activity

    summary = "Bot handler crashed"
    err = context.error
    if err is not None:
        summary = f"{type(err).__name__}: {err}"[:300]
    await log_bot_activity(
        kind="error",
        severity="error",
        summary=summary,
        user_id=user_id,
        chat_id=chat_id,
        error=err if isinstance(err, BaseException) else None,
    )

    if chat is None:
        return
    try:
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "Something broke on my side. Try again — the error is "
                "logged in <b>Bot → Activity</b> on the web app."
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        logger.exception("Failed to send error notice to chat=%s", chat.id)


def register_handlers(application: Application) -> None:
    application.add_error_handler(_on_error)
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("menu", cmd_menu))
    application.add_handler(CommandHandler("link", cmd_link))
    application.add_handler(CommandHandler("balance", cmd_balance))
    application.add_handler(CommandHandler("networth", cmd_networth))
    application.add_handler(CommandHandler("upcoming", cmd_upcoming))

    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("anniversary", cmd_anniversary_start)],
            states={
                ANNIV_AWAIT_DATE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, cmd_anniversary_received
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", cmd_cancel)],
        )
    )

    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("milestone", cmd_milestone_start)],
            states={
                MILESTONE_AWAIT_AMOUNT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, cmd_milestone_received
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", cmd_cancel)],
        )
    )

    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.PHOTO, on_photo_message))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_message)
    )
