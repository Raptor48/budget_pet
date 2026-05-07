"""
Notification producers — each function detects an alert condition and
``enqueue_notification`` it. They are deliberately read-only against the
domain repositories and write only to ``notifications_queue`` (+ a couple
of bot-only state tables for dedup/state).

Wired into the scheduler in :mod:`web.notifications.scheduler`.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

from web.bot_api.repo import get_bot_repo
from web.db import get_pool
from web.merchant_rules.keys import merchant_key as build_merchant_key
from web.notifications.queue import dedup_key_for, enqueue_notification
from web.transactions.display import normalize_transaction_title

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bank-artefact denylist. Plaid's recurring detector occasionally flags
# things that aren't really subscriptions: finance charges, monthly bank
# fees, self-transfers, generic ACH descriptors. Without this filter the
# morning brief turns into a wall of "New subscription detected: INTEREST
# CHARGE…" lines that the user can't act on. Keep substrings ALL-CAPS and
# specific enough that they only match bank junk, never real merchants.
# ---------------------------------------------------------------------------
_BANK_ARTEFACT_SUBSTRINGS = (
    "INTEREST CHARGE",
    "INTEREST CHARGED",
    "MONTHLY SERVICE FEE",
    "MAINTENANCE FEE",
    "OVERDRAFT FEE",
    "FOREIGN TRANSACTION FEE",
    "ATM FEE",
    "DDA TO DDA",  # Wells Fargo internal transfer
    "TRANSFER TO ",
    "TRANSFER FROM ",
    "INTERNAL TRANSFER",
    "WIRE TRANSFER",
    "ZELLE PAYMENT",
    "PAYMENT THANK YOU",  # credit-card auto-payment to itself
    "AUTOPAY PAYMENT",
)


def _looks_like_bank_artefact(name: str) -> bool:
    """True if ``name`` looks like a bank-internal descriptor rather than
    a real merchant. Used to suppress noise alerts."""
    if not name:
        return True
    upper = name.upper()
    return any(needle in upper for needle in _BANK_ARTEFACT_SUBSTRINGS)


# ---------------------------------------------------------------------------
# Brand canonicalization for subscription alerts. Plaid's recurring-stream
# descriptions still carry phone numbers, ACH IDs, state+date suffixes, and
# duplicated words even after the generic ACH cleaner. For the bot we want
# the simplest possible label ("Apple" not "Apple.com/bill CA 03/27"), so
# we run a small brand-override layer over the generic normalizer.
#
# Patterns are matched in order — list more specific patterns first so a
# multi-word match wins over a substring (e.g. ARCHDIGEST CONDENAST before
# CONDENAST alone).
# ---------------------------------------------------------------------------
_BRAND_OVERRIDES: tuple = (
    (re.compile(r"\bARCH(?:DIGEST|ITECTURAL\s+DIGEST)\b", re.I), "Architectural Digest"),
    (re.compile(r"\bCON\s*ED(?:ISON)?\b", re.I), "Con Edison"),
    (re.compile(r"\bUPSTART\b", re.I), "Upstart"),
    (re.compile(r"\bAPPLE(?:\.COM)?\b", re.I), "Apple"),
    (re.compile(r"\bPAYPAL\b", re.I), "PayPal"),
    (re.compile(r"\bAFFIRM\b", re.I), "Affirm"),
    (re.compile(r"\bADOBE\b", re.I), "Adobe"),
    (re.compile(r"\bSPECTRUM\b", re.I), "Spectrum"),
    (re.compile(r"\bPATREON\b", re.I), "Patreon"),
    (re.compile(r"\bRAILWAY(?:\.COM)?\b", re.I), "Railway"),
    (re.compile(r"\bNETFLIX\b", re.I), "Netflix"),
    (re.compile(r"\bSPOTIFY\b", re.I), "Spotify"),
    (re.compile(r"\bGITHUB\b", re.I), "GitHub"),
    (re.compile(r"\bAMAZON\b|\bAMZN\b", re.I), "Amazon"),
    (re.compile(r"\bGOOGLE\b|\bG\s*SUITE\b|\bGSUITE\b", re.I), "Google"),
)

_DUP_WORD_RE = re.compile(r"\b(\w+)\s+\1\b", re.I)


def _pretty_subscription_name(raw: str) -> str:
    """Bot-friendly merchant name for subscription alerts.

    1. Brand overrides win when the description contains a known SaaS/utility
       brand — collapses noisy bank descriptors to the canonical name.
    2. Otherwise falls back to ``normalize_transaction_title`` and additionally
       collapses duplicated consecutive words ("Spectrum Spectrum" → "Spectrum")
       which the generic cleaner doesn't dedupe.
    """
    if not raw:
        return raw or ""
    for pattern, canonical in _BRAND_OVERRIDES:
        if pattern.search(raw):
            return canonical
    cleaned = normalize_transaction_title({"description": raw})
    # Collapse "WORD WORD" → "WORD" repeatedly.
    while True:
        deduped = _DUP_WORD_RE.sub(r"\1", cleaned)
        if deduped == cleaned:
            break
        cleaned = deduped
    return cleaned


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
    """Fire "📅 expected tomorrow" forecasts for active recurring streams.

    Display name precedence in the payload:
      1. User alias from ``merchant_aliases`` (e.g. Flower → Rent).
      2. Brand-pretty name from ``_pretty_subscription_name`` (Patreon\\* …
         → Patreon).
      3. Raw ``description`` as a last resort.

    Without this layering the brief used to read like
    "Patreon\\* Membership Internet CA 04/01 expected tomorrow" — accurate
    but unreadable. ``recurring_streams`` carries only ``merchant_name``
    (no entity ID), so the alias join is restricted to the ``name:`` key
    namespace, matching the existing list_streams contract.
    """
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
            SELECT rs.id,
                   rs.description,
                   rs.merchant_name,
                   rs.frequency,
                   rs.average_amount_cents,
                   rs.last_date,
                   ma.display_name AS alias_display
            FROM recurring_streams rs
            LEFT JOIN merchant_aliases ma ON ma.merchant_key =
                'name:' || lower(NULLIF(TRIM(rs.merchant_name), ''))
            WHERE rs.is_active = TRUE
              AND rs.user_status = 'active'
              AND rs.last_date IS NOT NULL
            """,
        )
    for r in rows:
        # Advance from last_date to the next *future* expected charge using
        # the same helper the FE/forecast use. Plaid's last_date can be
        # several cadences behind, so a single +1 month is wrong.
        nxt = next_future_occurrence(r["last_date"], r["frequency"] or "")
        if nxt != target:
            continue
        raw = r["description"] or ""
        if _looks_like_bank_artefact(raw):
            # Skip bank-internal recurrences (auto-payments, fees) — same
            # rationale as in detect_subscription_changes.
            continue
        display_name = (
            r["alias_display"]
            or _pretty_subscription_name(raw)
            or raw
        )
        for u in users:
            uid = int(u["id"])
            if not await repo.is_alert_enabled(uid, "recurring_tomorrow"):
                continue
            new_id = await enqueue_notification(
                user_id=uid,
                type="recurring_tomorrow",
                priority="P1",
                payload={
                    "name": display_name,
                    "amount_cents": int(r["average_amount_cents"] or 0),
                    "due_date": str(target),
                    "stream_id": int(r["id"]),
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
    """Fire "🆕 first time at <merchant>" alerts.

    Keyed by the canonical ``merchant_key`` (``eid:<entity>`` when Plaid
    supplied an entity ID, otherwise ``name:<lower(merchant)>``) — the same
    contract used by ``merchant_aliases`` and ``merchant_category_rules``.

    Why not raw ``lower(merchant_name)`` like the legacy code did? Plaid
    occasionally returns minor variants of the same merchant (``Apple`` vs
    ``APPLE.COM/BILL`` vs ``Apple Inc.``). Each variant became its own
    ``merchant_seen`` row under the old key, so the "first time at Apple"
    alert fired multiple times. Using the structured merchant_key collapses
    those variants when an entity ID is present.

    The ``display_name`` we put in the payload prefers, in order:
    user alias (from ``merchant_aliases``) → cleaned-up Plaid name. The
    raw merchant_name is kept too so the rendering layer can fall back if
    the alias is removed later.
    """
    pool = await get_pool()
    repo = get_bot_repo()
    fired = 0
    async with pool.acquire() as conn:
        users = await conn.fetch(
            "SELECT id FROM users WHERE telegram_chat_id IS NOT NULL"
        )
        if not users:
            return 0
        # Pull a per-(entity, account-owner) slice of recent expense
        # transactions. We DISTINCT on the canonical merchant_key — built
        # from merchant_entity_id when Plaid supplied one — so the same
        # merchant under two name variants doesn't ride two rows. The
        # ``2 days`` window is just lag-tolerance for late Plaid syncs;
        # actual deduping is done by ``merchant_seen`` per canonical key.
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (
                CASE
                    WHEN NULLIF(TRIM(t.merchant_entity_id), '') IS NOT NULL
                        THEN 'eid:' || lower(t.merchant_entity_id)
                    ELSE 'name:' || lower(t.merchant_name)
                END
            )
                   t.merchant_name,
                   t.merchant_entity_id,
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
            ORDER BY
                CASE
                    WHEN NULLIF(TRIM(t.merchant_entity_id), '') IS NOT NULL
                        THEN 'eid:' || lower(t.merchant_entity_id)
                    ELSE 'name:' || lower(t.merchant_name)
                END,
                t.date DESC
            """,
        )
    for r in rows:
        merchant = (r["merchant_name"] or "").strip()
        if not merchant:
            continue
        # Skip bank-internal artefacts (interest, fees, transfers). Plaid
        # sometimes leaves these in merchant_name when enrichment misses.
        if _looks_like_bank_artefact(merchant):
            continue
        # Skip micro-charges — almost never a real first-merchant moment.
        if int(r["amount_cents"] or 0) < 100:
            continue
        canonical = build_merchant_key(
            merchant_entity_id=r["merchant_entity_id"],
            merchant_name=merchant,
        )
        if not canonical:
            continue
        sighting = await repo.remember_merchant(canonical)
        if not sighting.get("new"):
            continue
        await repo.mark_merchant_notified(canonical)
        # User-chosen rename wins over the Plaid label. Falls back to the
        # cleaned merchant name so old transactions without enrichment still
        # render reasonably.
        alias = await repo.resolve_merchant_alias(canonical)
        display_name = alias or _pretty_subscription_name(merchant) or merchant
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
                    "merchant_name": display_name,
                    "raw_merchant_name": merchant,
                    "merchant_key": canonical,
                    "amount_cents": int(r["amount_cents"] or 0),
                },
                dedup_key=dedup_key_for("new_merchant", canonical, uid),
            )
            if new_id:
                fired += 1
    return fired


# ---------------------------------------------------------------------------
# Subscription creep + price hike — leverage recurring_price_snapshots
# ---------------------------------------------------------------------------


async def detect_subscription_changes() -> int:
    """Fire two distinct alerts off ``recurring_streams``:

    * **First detection** — emitted at most once per stream lifetime,
      gated by ``recurring_streams.subscription_alerted_at``. Without this
      gate the ``recurring_price_snapshots`` table only inserts on a delta,
      so a stable Netflix has ``len(history) == 1`` forever, the producer
      reads ``prev_amount = None``, and the 24h queue dedup expires every
      morning — yielding "🆕 N new subscriptions" daily. The persistent
      stamp breaks that loop.
    * **Price change** — fires whenever Plaid reports a different
      ``last_amount_cents`` than the previous snapshot. Unaffected by
      the first-detection stamp.

    Both alerts go out as ``subscription_creep`` notifications; ``builders``
    distinguishes them by the presence of ``previous_amount_cents``.
    """
    pool = await get_pool()
    repo = get_bot_repo()
    fired = 0
    async with pool.acquire() as conn:
        # ``alias_display`` resolves the user-chosen rename (Flower → Rent)
        # via the same name-keyed alias used elsewhere. recurring_streams
        # only carries merchant_name (no entity ID) so we restrict the join
        # to the ``name:`` namespace, matching the SQL contract used by
        # ``recurring/repo.py::list_streams``.
        streams = await conn.fetch(
            """
            SELECT rs.id,
                   rs.description,
                   rs.merchant_name,
                   rs.last_amount_cents,
                   rs.subscription_alerted_at,
                   ma.display_name AS alias_display
            FROM recurring_streams rs
            LEFT JOIN merchant_aliases ma ON ma.merchant_key =
                'name:' || lower(NULLIF(TRIM(rs.merchant_name), ''))
            WHERE rs.is_active = TRUE AND rs.user_status = 'active'
              AND rs.last_amount_cents IS NOT NULL
            """,
        )
        users = await conn.fetch(
            "SELECT id FROM users WHERE telegram_chat_id IS NOT NULL"
        )
    for s in streams:
        raw_description = s["description"] or ""
        # Filter out bank artefacts (interest charges, fees, self-transfers).
        # Plaid's recurring detector sometimes catches these as "subscriptions"
        # because they repeat monthly, but they are not actionable for the user.
        if _looks_like_bank_artefact(raw_description):
            continue
        # User alias > brand-pretty (Patreon* → Patreon) > raw description.
        # Resolved once at enqueue time so the brief never has to JOIN.
        pretty_name = (
            s["alias_display"]
            or _pretty_subscription_name(raw_description)
        )

        history = await repo.get_recurring_price_history(int(s["id"]), limit=2)
        prev_amount = None
        if history and len(history) >= 2:
            # Most recent snapshot (history[0]) is the current; history[1]
            # is the previous price to compare against.
            prev_amount = int(history[1]["amount_cents"])
        # Always record the current price; helper is no-op when unchanged.
        await repo.record_recurring_amount(
            int(s["id"]), int(s["last_amount_cents"])
        )

        is_first_detection = prev_amount is None
        is_price_change = (
            prev_amount is not None and prev_amount != int(s["last_amount_cents"])
        )

        if is_first_detection and s["subscription_alerted_at"] is not None:
            # Already alerted about this stream once. The 24h dedup would
            # have re-fired this every morning before the stamp existed.
            continue
        if not is_first_detection and not is_price_change:
            # Stable stream, nothing to say.
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
                    "name": pretty_name,
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
        if is_first_detection:
            # Stamp regardless of whether anyone was actually notified —
            # otherwise a user who later enables the alert would still get
            # the historical flood. The stamp is "we *would have* alerted".
            await repo.mark_subscription_alerted(int(s["id"]))
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
