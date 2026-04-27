"""
Telegram bot handlers — menus, commands, callback queries.

UX rules:
    * One main menu, English-only, six top buttons.
    * Every screen offers a "Back" route. Reach Main with /menu or the back
      stack — never let the user get lost.
    * Callback data is short — ``action[:arg[:arg]]`` — Telegram caps
      callback_data at 64 bytes.
    * Long-form input (mood note, anniversary date, milestone amount) uses
      a tiny ``ConversationHandler`` state machine.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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


def _main_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("💰 Cash", callback_data="menu:cash"),
            InlineKeyboardButton("📊 Today", callback_data="menu:today"),
            InlineKeyboardButton("🔔 Alerts", callback_data="menu:alerts"),
        ],
        [
            InlineKeyboardButton("👥 Family", callback_data="menu:family"),
            InlineKeyboardButton("🎯 Goals", callback_data="menu:goals"),
            InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def _back_kb(target: str = "menu:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data=target)]])


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
        await update.message.reply_text(
            f"Welcome back, {user['username']} 👋\nPick a section:",
            reply_markup=_main_menu_kb(),
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
    await update.message.reply_text("Main menu:", reply_markup=_main_menu_kb())


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
    await update.message.reply_text(
        f"Linked ✅ Welcome, {user['username']}!", reply_markup=_main_menu_kb()
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
    elif head == "mood":
        await _on_mood(query, user, parts)
    elif head == "tea":
        await _on_tea(query, user, parts)
    elif head == "reauth":
        await _on_reauth(query, user, parts)
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
            "💰 <b>Cash</b>\nTap <b>Type</b> for a quick entry, or <b>Receipt</b> "
            "to upload a photo.",
            reply_markup=_cash_menu_kb(),
            parse_mode=ParseMode.HTML,
        )
    elif section == "today":
        from web.bot_api.repo import get_bot_repo

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
            "<b>Recent cash entries</b>\n\n" + "\n".join(rows)
            if rows
            else "No cash entries yet."
        )
        await query.edit_message_text(
            text, reply_markup=_back_kb("menu:cash"), parse_mode=ParseMode.HTML
        )
    else:
        await query.edit_message_text("💰 <b>Cash</b>", reply_markup=_cash_menu_kb(), parse_mode=ParseMode.HTML)


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
        await query.edit_message_text(
            "🧹 Manage chores in the web app → <b>Bot</b> page → Chores.",
            reply_markup=_back_kb("menu:family"),
            parse_mode=ParseMode.HTML,
        )
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
            text = "No milestones yet. Use /milestone <amount> to add one."
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


async def _on_mood(query, user, parts):
    """Inline buttons attached to a mood-check brief: ``mood:<txn_id>:<value>``."""
    if len(parts) < 3:
        return
    try:
        txn_id = int(parts[1])
    except ValueError:
        return
    mood = parts[2]
    if mood not in {"happy", "meh", "regret"}:
        return
    await get_bot_repo().upsert_mood(txn_id, user["id"], mood)
    emoji = {"happy": "👍", "meh": "🤷", "regret": "👎"}[mood]
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await query.message.reply_text(f"Logged {emoji}")


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


async def _on_reauth(query, user, parts):
    item_id = parts[1] if len(parts) > 1 else ""
    base = (await _frontend_base_url())
    url = f"{base}/settings#bank-{item_id}" if item_id else f"{base}/settings"
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        f"Open {url} to re-link the bank.", disable_web_page_preview=False
    )


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
        await update.message.reply_text("Net worth not yet computed.")
        return
    await update.message.reply_text(
        f"📈 Net worth: <b>{_money(nw)}</b>", parse_mode=ParseMode.HTML
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
        lines.append(
            f"• {r['next_date']} — {r['name']} {_money(int(r['amount_cents']))}"
        )
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML
    )


# ---------------------------------------------------------------------------
# Cash quick-entry — text "AMT description" → cash transaction
# ---------------------------------------------------------------------------


async def on_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_linked(update)
    if not user:
        return
    txt = (update.message.text or "").strip()
    if not txt:
        return
    parsed = _parse_cash_entry(txt)
    if parsed is None:
        await update.message.reply_text(
            "Try <code>5 coffee</code> or <code>120 grocery</code>.",
            parse_mode=ParseMode.HTML,
        )
        return
    amount_cents, name = parsed
    try:
        result = await _post_cash_transaction(user, amount_cents, name)
    except RuntimeError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(
        f"💸 Logged <b>{result['name']}</b> {_money(amount_cents)}",
        parse_mode=ParseMode.HTML,
    )


# ---------------------------------------------------------------------------
# Receipt photo → OCR → cash transaction (no split for MVP)
# ---------------------------------------------------------------------------


async def on_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _ensure_linked(update)
    if not user:
        return
    photo = update.message.photo[-1]  # largest
    file = await context.bot.get_file(photo.file_id)
    bio = bytearray()
    await file.download_to_memory(out=bio)  # type: ignore[arg-type]
    image_bytes = bytes(bio)
    await update.message.reply_text("📸 Scanning receipt…")
    try:
        from web.telegram.ocr import extract_receipt

        parsed = await extract_receipt(image_bytes)
    except Exception as exc:
        logger.exception("OCR failed")
        await update.message.reply_text(f"OCR failed: {exc}")
        return
    if not parsed or not parsed.get("total_cents"):
        await update.message.reply_text(
            "Couldn't read a total off this receipt. Try a clearer photo."
        )
        return
    name = parsed.get("merchant_name") or "Receipt"
    try:
        txn = await _post_cash_transaction(
            user,
            int(parsed["total_cents"]),
            name,
            receipt_image=image_bytes,
            receipt_image_mime="image/jpeg",
            receipt_lines=parsed.get("lines"),
            receipt_merchant=parsed.get("merchant_name"),
            receipt_date=parsed.get("date"),
            tax_cents=parsed.get("tax_cents"),
            raw_ocr_json=parsed,
        )
    except RuntimeError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(
        f"📸 Saved <b>{name}</b> for {_money(int(parsed['total_cents']))}",
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
    """Parse free-text "5 coffee" / "5.50 latte" / "12,50 lunch" entries."""
    parts = text.strip().split(None, 1)
    if not parts:
        return None
    raw = parts[0].replace(",", ".").replace("$", "")
    try:
        amount = float(raw)
    except ValueError:
        return None
    if amount <= 0:
        return None
    name = parts[1] if len(parts) > 1 else "Cash spend"
    return int(round(amount * 100)), name.strip()


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


async def _today_snapshot(user_id: int) -> str:
    """Tiny dashboard read — totals across cash + Plaid accounts."""
    from web.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT COALESCE(SUM(current_balance_cents), 0) AS total,
                   COUNT(*) AS n
            FROM accounts
            WHERE is_active = TRUE
            """
        )
    total = int(rows[0]["total"]) if rows else 0
    n = int(rows[0]["n"]) if rows else 0
    return (
        f"📊 <b>Today</b>\nAccounts: {n}\nNet balance: {_money(total)}\n\n"
        "Use /upcoming for next charges, /networth for the headline number."
    )


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


async def _upcoming_recurring(days: int = 14) -> List[Dict[str, Any]]:
    from web.db import get_pool

    pool = await get_pool()
    target = date.today() + timedelta(days=days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT description AS name, average_amount_cents AS amount_cents,
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
                "name": r["name"],
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
    receipt_image: Optional[bytes] = None,
    receipt_image_mime: Optional[str] = None,
    receipt_lines: Optional[List[Dict[str, Any]]] = None,
    receipt_merchant: Optional[str] = None,
    receipt_date: Optional[date] = None,
    tax_cents: Optional[int] = None,
    raw_ocr_json: Optional[Any] = None,
) -> Dict[str, Any]:
    """Insert a manual cash transaction. Picks the user's primary cash wallet
    (by account.user_id if set, else the first non-Plaid account)."""
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
    txn = await repo.create_cash_transaction(
        {
            "account_id": wallet["id"],
            "amount_cents": amount_cents,
            "currency": "USD",
            "date": date.today(),
            "name": name,
            "merchant_name": receipt_merchant,
            "source": "manual",
        }
    )
    if receipt_image:
        await get_bot_repo().create_receipt(
            user_id=user["id"],
            image_data=receipt_image,
            image_mime=receipt_image_mime or "image/jpeg",
            merchant_name=receipt_merchant,
            receipt_date=receipt_date,
            total_cents=amount_cents,
            tax_cents=tax_cents,
            raw_ocr_json=raw_ocr_json,
            transaction_id=txn["id"],
            lines=receipt_lines,
        )
    return txn


# ---------------------------------------------------------------------------
# Wire-up
# ---------------------------------------------------------------------------


def register_handlers(application: Application) -> None:
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
