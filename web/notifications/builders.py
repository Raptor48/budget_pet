"""
Translate a queued notification (or a bundle of them) into a Telegram
message + reply markup.

These functions never touch I/O — they're pure formatters. The dispatcher
calls :func:`build_single` for P0 alerts and :func:`build_brief` for
P1 / P2 batches.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple


def _money(cents: int, currency: str = "USD") -> str:
    sign = "-" if cents < 0 else ""
    val = abs(cents) / 100.0
    if currency == "USD":
        return f"{sign}${val:,.2f}"
    return f"{sign}{val:,.2f} {currency}"


def _line(prefix: str, body: str) -> str:
    return f"{prefix} {body}"


# ---------------------------------------------------------------------------
# Per-event renderers — one section/line for each type.
# Returns (HTML string, optional inline keyboard markup as list of rows,
# where each row is list of (text, callback_data) tuples).
# ---------------------------------------------------------------------------

def _render_budget_threshold(payload: Dict[str, Any]) -> str:
    cat = payload.get("category_name", "Budget")
    pct = payload.get("percent_used", 0)
    over_cents = payload.get("over_cents", 0)
    return _line(
        "📊",
        f"<b>{cat}</b> {pct:.0f}% of budget — over by {_money(over_cents)}",
    )


def _render_recurring_tomorrow(payload: Dict[str, Any]) -> str:
    name = payload.get("name", "Recurring")
    amount = payload.get("amount_cents", 0)
    return _line("📅", f"<b>{name}</b> {_money(amount)} expected tomorrow")


def _render_plaid_reauth(payload: Dict[str, Any]) -> Tuple[str, List[List[Tuple[str, str]]]]:
    inst = payload.get("institution_name", "your bank")
    return (
        _line("🔌", f"<b>{inst}</b> needs to be re-authorised."),
        [[("Re-link", f"reauth:{payload.get('item_id', '')}")]],
    )


def _render_new_merchant(payload: Dict[str, Any]) -> str:
    name = payload.get("merchant_name", "New merchant")
    amount = payload.get("amount_cents", 0)
    return _line(
        "🆕",
        f"First time at <b>{name}</b> — {_money(amount)}.",
    )


def _render_subscription_creep(payload: Dict[str, Any]) -> str:
    name = payload.get("name", "Subscription")
    cur = payload.get("amount_cents", 0)
    prev = payload.get("previous_amount_cents")
    if prev is None:
        return _line("🔁", f"New subscription detected: <b>{name}</b> {_money(cur)}.")
    delta_pct = ((cur - prev) / max(prev, 1)) * 100
    return _line(
        "📈",
        f"<b>{name}</b> price changed: {_money(prev)} → {_money(cur)} "
        f"({delta_pct:+.0f}%)",
    )


def _render_milestone(payload: Dict[str, Any]) -> str:
    threshold = payload.get("threshold_cents", 0)
    label = payload.get("label") or "Milestone"
    return _line(
        "🎉",
        f"You crossed {_money(threshold)} net worth — {label}!",
    )


def _render_leaderboard(payload: Dict[str, Any]) -> str:
    entries = payload.get("entries", [])
    if not entries:
        return ""
    lines = ["🏆 <b>Top of the week</b>"]
    for e in entries[:6]:
        lines.append(
            f"• {e.get('username', '?')} — {e.get('category_name', '?')} "
            f"{_money(int(e.get('amount_cents', 0)))}"
        )
    return "\n".join(lines)


def _render_streak_milestone(payload: Dict[str, Any]) -> str:
    label = payload.get("label", "Streak")
    count = payload.get("count", 0)
    return _line("🔥", f"<b>{label}</b>: {count} in a row")


def _render_anniversary(payload: Dict[str, Any]) -> str:
    days = int(payload.get("days_until") or 0)
    years = int(payload.get("years") or 0)
    year_part = f" — {years} year{'' if years == 1 else 's'} together" if years > 0 else ""
    if days == 0:
        return _line("💌", f"<b>Happy anniversary!</b>{year_part}")
    return _line(
        "💌",
        f"Anniversary in <b>{days} days</b>{year_part}. Time to plan something.",
    )


def _render_test_alert(payload: Dict[str, Any]) -> str:
    """End-to-end probe — verifies queue → dispatcher → Telegram works.
    Triggered manually from /bot → Overview → Send test alert."""
    requested_by = payload.get("requested_by") or "you"
    return (
        "🧪 <b>Test alert</b>\n"
        f"If you can read this, the full pipeline is alive — queue, "
        f"dispatcher, and the Telegram bot are talking. Requested by "
        f"<i>{requested_by}</i>."
    )


_RENDERERS = {
    "budget_threshold": _render_budget_threshold,
    "recurring_tomorrow": _render_recurring_tomorrow,
    "plaid_reauth": _render_plaid_reauth,
    "new_merchant": _render_new_merchant,
    "subscription_creep": _render_subscription_creep,
    "milestone": _render_milestone,
    "leaderboard": _render_leaderboard,
    "streak_milestone": _render_streak_milestone,
    "anniversary": _render_anniversary,
    "test_alert": _render_test_alert,
}


def render_event(notification: Dict[str, Any]):
    """Return ``(text, keyboard)`` for a single queued row."""
    type_ = notification.get("type")
    payload = notification.get("payload") or {}
    fn = _RENDERERS.get(type_)
    if fn is None:
        return (f"({type_}) — no renderer", [])
    out = fn(payload)
    if isinstance(out, tuple):
        return out
    return (out, [])


# ---------------------------------------------------------------------------
# Single-event message (P0)
# ---------------------------------------------------------------------------

def build_single(notification: Dict[str, Any]) -> Tuple[str, List[List[Tuple[str, str]]]]:
    text, keyboard = render_event(notification)
    return (text, keyboard)


# ---------------------------------------------------------------------------
# Brief (P1 daily / P2 sunday) — sectioned digest
# ---------------------------------------------------------------------------

_SECTION_ORDER = [
    ("plaid_reauth", "🚨 Needs attention"),
    ("budget_threshold", "📊 Budget"),
    ("subscription_creep", "🔁 Subscriptions"),
    ("recurring_tomorrow", "📅 Recurring"),
    ("new_merchant", "🆕 New merchants"),
    ("milestone", "🎉 Milestones"),
    ("streak_milestone", "🔥 Streaks"),
    ("anniversary", "💌 Anniversary"),
    ("leaderboard", "🏆 Leaderboard"),
]

_TOP_N_PER_SECTION = 5  # show top N by amount, collapse the rest


def _format_subscription_section(items: List[Dict[str, Any]]) -> List[str]:
    """Aggregate subscription_creep events into a single bulleted section.

    Brand-new subscriptions (prev=None) collapse into one heading with a
    total + top-N bullet list + "and N more"; price changes get a one-line
    each since they're rarer and individually meaningful.
    """
    new_subs: List[Dict[str, Any]] = []
    price_changes: List[Dict[str, Any]] = []
    for item in items:
        payload = item.get("payload") or {}
        if payload.get("previous_amount_cents") is None:
            new_subs.append(payload)
        else:
            price_changes.append(payload)

    out: List[str] = []
    if new_subs:
        # De-duplicate by name+amount within the same brief — Plaid sometimes
        # emits the same subscription under two slightly different descriptors
        # in one window.
        seen: set = set()
        unique: List[Dict[str, Any]] = []
        for p in new_subs:
            key = (str(p.get("name", "")).lower(), int(p.get("amount_cents", 0)))
            if key in seen:
                continue
            seen.add(key)
            unique.append(p)
        unique.sort(key=lambda p: int(p.get("amount_cents", 0)), reverse=True)
        total = sum(int(p.get("amount_cents", 0)) for p in unique)
        plural = "s" if len(unique) != 1 else ""
        out.append(
            f"🔁 <b>Subscriptions</b> — {len(unique)} new, "
            f"{_money(total)} total"
        )
        for p in unique[:_TOP_N_PER_SECTION]:
            out.append(
                f"  • <b>{p.get('name', '?')}</b> — "
                f"{_money(int(p.get('amount_cents', 0)))}"
            )
        remainder = len(unique) - _TOP_N_PER_SECTION
        if remainder > 0:
            out.append(f"  • +{remainder} more")

    for p in price_changes:
        cur = int(p.get("amount_cents", 0))
        prev = int(p.get("previous_amount_cents") or 0)
        delta_pct = ((cur - prev) / max(prev, 1)) * 100
        out.append(
            f"📈 <b>{p.get('name', '?')}</b> "
            f"{_money(prev)} → {_money(cur)} ({delta_pct:+.0f}%)"
        )
    return out


def _format_new_merchant_section(items: List[Dict[str, Any]]) -> List[str]:
    """Aggregate new_merchant events: heading with total + top-N bullets."""
    payloads = [item.get("payload") or {} for item in items]
    payloads.sort(key=lambda p: int(p.get("amount_cents", 0)), reverse=True)
    total = sum(int(p.get("amount_cents", 0)) for p in payloads)
    out: List[str] = [
        f"🆕 <b>New merchants</b> — {len(payloads)} this week, "
        f"{_money(total)} total"
    ]
    for p in payloads[:_TOP_N_PER_SECTION]:
        out.append(
            f"  • <b>{p.get('merchant_name', '?')}</b> — "
            f"{_money(int(p.get('amount_cents', 0)))}"
        )
    remainder = len(payloads) - _TOP_N_PER_SECTION
    if remainder > 0:
        out.append(f"  • +{remainder} more")
    return out


# Sections whose items are merged into a single rendered block. Sections
# absent from this map fall back to default per-item rendering.
_SECTION_FORMATTERS = {
    "subscription_creep": _format_subscription_section,
    "new_merchant": _format_new_merchant_section,
}


def build_brief(
    *,
    title: str,
    notifications: List[Dict[str, Any]],
    streak_summary: Optional[List[Dict[str, Any]]] = None,
    audit_invite: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[List[Tuple[str, str]]]]:
    """Compose a multi-section message from a batch of notifications.

    ``streak_summary`` is the user-streaks list (optional, mainly Sunday).
    ``audit_invite`` adds the Sunday "What tea?" question with inline buttons.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for n in notifications:
        grouped.setdefault(n["type"], []).append(n)

    lines: List[str] = [f"<b>{title}</b>"]
    keyboard: List[List[Tuple[str, str]]] = []

    for type_, heading in _SECTION_ORDER:
        items = grouped.get(type_) or []
        if not items:
            continue
        formatter = _SECTION_FORMATTERS.get(type_)
        if formatter is not None:
            block = formatter(items)
            if block:
                lines.append("")
                lines.extend(block)
            continue
        lines.append("")
        lines.append(heading)
        for item in items:
            text, kb = render_event(item)
            if not text:
                continue
            lines.append(text)
            for row in kb:
                keyboard.append(row)

    # Streak summary (Sunday only — caller decides).
    if streak_summary:
        active = [s for s in streak_summary if s.get("current_count", 0) > 0]
        if active:
            lines.append("")
            lines.append("🔥 Streaks")
            for s in active[:5]:
                lines.append(
                    f"• {s.get('label', '?')} — {s.get('current_count', 0)}"
                )

    if audit_invite:
        lines.append("")
        lines.append("☕ <b>Audit Sunday</b>")
        if audit_invite.get("local_time"):
            lines.append(f"Today at {audit_invite['local_time']}")
        lines.append("What tea are we brewing?")
        keyboard.append(
            [
                ("Earl Grey", "tea:earl_grey"),
                ("Sencha", "tea:sencha"),
                ("Skip today", "tea:skip"),
            ]
        )

    if len(lines) == 1:
        # Nothing to report — caller should skip sending entirely.
        return ("", [])
    return ("\n".join(lines), keyboard)


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def format_local_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def format_short_date(d: date) -> str:
    return d.strftime("%b %d")
