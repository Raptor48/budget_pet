"""Per-card insight builders.

Each ``build_<card_type>`` helper returns a list of card dicts in the shape
documented in ``docs/insights-math.md``. Splitting builders out of
``feed.py`` keeps the orchestrator small and the individual rules
testable in isolation.

All helpers are pure async functions — they only touch repositories
explicitly passed in (or construct them lazily when convenient).
They must **never** raise. Any unexpected error is logged by the caller
via ``try / except`` around each helper invocation.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_card(
    *,
    type: str,
    severity: str,
    title: str,
    summary: str,
    detail: Optional[str],
    dedupe_key: str,
    action_url: Optional[str] = None,
    action_label: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "type": type,
        "severity": severity,
        "title": title,
        "summary": summary,
        "detail": detail,
        "dedupe_key": dedupe_key,
        "action_url": action_url,
        "action_label": action_label,
    }


def _fmt_usd(cents: int) -> str:
    return f"${cents / 100:,.0f}"


def _stream_label(stream: Dict[str, Any]) -> str:
    return (
        (stream.get("user_label") or "").strip()
        or stream.get("display_title")
        or stream.get("merchant_name")
        or stream.get("description")
        or "Subscription"
    )


# ---------------------------------------------------------------------------
# budget_risk
# ---------------------------------------------------------------------------

BUDGET_RISK_RATIO = 0.90  # warn when actual/limit >= 90% and day-of-month share < 80%


def build_budget_risk(
    progress_rows: Iterable[Dict[str, Any]],
    month: str,
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Flag budgets at risk (>=90% with the month still young) or over.

    ``progress_rows`` is the output of ``BudgetsRepository.get_progress``.
    The card is emitted per-budget so users can dismiss individually in
    Phase 4.
    """
    today = today or date.today()
    cards: List[Dict[str, Any]] = []
    # Progress of the month (0..1). Month-end returns 1; day 1 returns ~1/30.
    import calendar

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    day_of_month_share = today.day / days_in_month

    for row in progress_rows:
        budget_cents = int(row.get("budget_cents") or 0)
        actual_cents = int(row.get("actual_cents") or 0)
        if budget_cents <= 0:
            continue
        ratio = actual_cents / budget_cents
        over = actual_cents >= budget_cents
        at_risk = ratio >= BUDGET_RISK_RATIO and day_of_month_share < 0.80
        if not (over or at_risk):
            continue
        category_name = row.get("category_name") or "Category"
        overage = actual_cents - budget_cents
        if over:
            summary = (
                f"Over {category_name} budget by {_fmt_usd(max(0, overage))}"
                f" ({_fmt_usd(actual_cents)} / {_fmt_usd(budget_cents)})"
            )
            severity = "warn"
        else:
            summary = (
                f"{category_name} at {int(ratio * 100)}% with "
                f"{int((1 - day_of_month_share) * 100)}% of the month left"
            )
            severity = "warn"
        cards.append(
            make_card(
                type="budget_risk",
                severity=severity,
                title="Budget at risk" if not over else "Budget exceeded",
                summary=summary,
                detail=(
                    f"{_fmt_usd(actual_cents)} spent of {_fmt_usd(budget_cents)} "
                    f"by day {today.day} of {days_in_month}."
                ),
                dedupe_key=f"budget_risk:{row.get('id')}:{month}",
                action_url=f"/budgets?month={month}",
                action_label="Open budgets",
            )
        )
    # Cap to top-3 by absolute overage or highest ratio so the card list stays useful.
    cards.sort(
        key=lambda c: (
            0 if "exceeded" in c["title"].lower() else 1,
            -int("".join(ch for ch in c["summary"] if ch.isdigit()) or "0"),
        )
    )
    return cards[:3]


# ---------------------------------------------------------------------------
# category_trend
# ---------------------------------------------------------------------------

CATEGORY_TREND_PCT = 0.25
CATEGORY_TREND_MIN_CENTS = 2_000  # skip tiny categories ($20) to avoid noise


def build_category_trend(
    rolling_rows: Iterable[Dict[str, Any]],
    month: str,
) -> List[Dict[str, Any]]:
    """Emit one warn card per category spiking >= 25% over its 3-mo average.

    Skips rows with no prior history, tiny ($<20) current spend, or
    decreases (good news — not emitted for now).
    """
    cards: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    for r in rolling_rows:
        cur = int(r.get("current_cents") or 0)
        avg = int(r.get("avg_cents") or 0)
        if cur < CATEGORY_TREND_MIN_CENTS:
            continue
        if avg <= 0:
            continue
        if int(r.get("prior_months") or 0) == 0:
            continue
        delta = cur / avg - 1
        if delta >= CATEGORY_TREND_PCT:
            candidates.append({**r, "delta": delta, "cur": cur, "avg": avg})

    candidates.sort(key=lambda x: x["delta"], reverse=True)
    for r in candidates[:5]:  # top 5 categories by spend, per plan
        pct = int(r["delta"] * 100)
        name = r.get("category_name") or "Category"
        cat_id = r.get("category_id")
        cards.append(
            make_card(
                type="category_trend",
                severity="warn",
                title=f"{name} up {pct}%",
                summary=(
                    f"{name} up {pct}% vs 3-mo avg "
                    f"({_fmt_usd(r['cur'])} vs {_fmt_usd(r['avg'])})"
                ),
                detail="Rolling average of the three completed months.",
                dedupe_key=f"category_trend:{cat_id}:{month}",
                action_url=(
                    f"/reports?tab=category&category={cat_id}" if cat_id else "/reports?tab=category"
                ),
                action_label="Open category",
            )
        )
    return cards


# ---------------------------------------------------------------------------
# missed_recurring
# ---------------------------------------------------------------------------

MISSED_RECURRING_MIN_GRACE = timedelta(days=3)


def _freq_period_days(freq: str) -> Optional[int]:
    f = (freq or "").upper()
    return {
        "WEEKLY": 7,
        "BIWEEKLY": 14,
        "SEMI_MONTHLY": 15,
        "MONTHLY": 30,
        "ANNUALLY": 365,
    }.get(f)


def build_missed_recurring(
    streams: Iterable[Dict[str, Any]],
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Outflow streams that haven't charged by expected date + grace window.

    Grace = max(3 days, 20% of the period), clamped so weekly streams are
    flagged fast and annual streams get a generous buffer.
    """
    from web.reports.calculations import next_occurrence

    today = today or date.today()
    cards: List[Dict[str, Any]] = []
    for s in streams:
        if not s.get("is_active"):
            continue
        if (s.get("status") or "").upper() == "TOMBSTONED":
            continue
        if s.get("direction") != "outflow":
            continue
        last_date = s.get("last_date")
        if not last_date:
            continue
        if isinstance(last_date, str):
            try:
                last_date = date.fromisoformat(last_date)
            except ValueError:
                continue
        freq = s.get("frequency") or ""
        expected = next_occurrence(last_date, freq)
        if not expected:
            continue
        period_days = _freq_period_days(freq) or 30
        grace = max(MISSED_RECURRING_MIN_GRACE, timedelta(days=int(period_days * 0.2)))
        if today <= expected + grace:
            continue  # not late yet
        label = _stream_label(s)
        amount = int(s.get("last_amount_cents") or s.get("average_amount_cents") or 0)
        cards.append(
            make_card(
                type="missed_recurring",
                severity="warn",
                title="Recurring charge missing",
                summary=(
                    f"{label} ({_fmt_usd(amount)}) not charged since "
                    f"{last_date.isoformat()} (expected ~{expected.isoformat()})"
                ),
                detail=(
                    f"Based on a {freq.lower() or 'recurring'} cadence. "
                    f"Grace window: {grace.days} day(s)."
                ),
                dedupe_key=f"missed_recurring:{s.get('id')}:{expected.isoformat()}",
                action_url="/recurring",
                action_label="Review recurring",
            )
        )
    return cards[:5]


# ---------------------------------------------------------------------------
# duplicate_subscription
# ---------------------------------------------------------------------------

DUPLICATE_SIMILARITY_PCT = 0.20  # amounts must be within 20% of each other
DUPLICATE_MIN_MONTHLY_CENTS = 500  # $5 combined floor


def _merchant_token(s: Dict[str, Any]) -> Optional[str]:
    raw = (
        (s.get("merchant_name") or "").strip()
        or (s.get("description") or "").strip()
    )
    if not raw:
        return None
    raw = raw.lower()
    # Take first alphanumeric word; strip punctuation / trailing IDs like "#1234".
    m = re.search(r"[a-z0-9]+", raw)
    return m.group(0) if m else None


def build_duplicate_subscription(
    streams: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Group active outflow streams by first merchant token; warn on near-duplicates."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for s in streams:
        if not s.get("is_active"):
            continue
        if (s.get("status") or "").upper() == "TOMBSTONED":
            continue
        if s.get("direction") != "outflow":
            continue
        tok = _merchant_token(s)
        if not tok:
            continue
        groups.setdefault(tok, []).append(s)

    cards: List[Dict[str, Any]] = []
    for tok, items in groups.items():
        if len(items) < 2:
            continue
        amounts = [int(s.get("last_amount_cents") or 0) for s in items]
        if not all(a > 0 for a in amounts):
            continue
        big = max(abs(a) for a in amounts)
        small = min(abs(a) for a in amounts)
        if big == 0:
            continue
        if (big - small) / big > DUPLICATE_SIMILARITY_PCT:
            continue
        # Require at least two distinct stream ids (guards against upserts
        # returning the same row twice in edge cases).
        ids = sorted({str(s.get("id")) for s in items if s.get("id")})
        if len(ids) < 2:
            continue
        total_monthly = sum(amounts)
        if total_monthly < DUPLICATE_MIN_MONTHLY_CENTS:
            continue
        labels = ", ".join(_stream_label(s) for s in items[:3])
        summary = (
            f"Possible duplicate: {labels} ({_fmt_usd(amounts[0])} each)"
        )
        cards.append(
            make_card(
                type="duplicate_subscription",
                severity="warn",
                title="Duplicate subscription?",
                summary=summary,
                detail=(
                    f"{len(items)} streams share the merchant token '{tok}' "
                    f"with amounts within {int(DUPLICATE_SIMILARITY_PCT * 100)}%."
                ),
                dedupe_key=f"duplicate:{','.join(ids)}",
                action_url="/recurring",
                action_label="Review recurring",
            )
        )
    return cards[:5]


# ---------------------------------------------------------------------------
# overdue_account + high_utilization
# ---------------------------------------------------------------------------

UTIL_WARN_THRESHOLD = 0.75
UTIL_INFO_THRESHOLD = 0.30


def build_overdue_and_utilization(
    accounts: Iterable[Dict[str, Any]],
    viewer_user_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Per-account overdue and credit-utilization cards.

    ``accounts`` is the raw ``AccountsRepository.list_accounts(active_only=True)``
    output. When ``viewer_user_id`` is supplied, accounts owned by another
    family member are skipped (shared accounts with ``user_id IS NULL``
    remain visible).
    """
    cards: List[Dict[str, Any]] = []
    for a in accounts:
        if not a.get("is_active"):
            continue
        owner = a.get("user_id")
        if viewer_user_id is not None and owner is not None and owner != viewer_user_id:
            continue

        name = a.get("name") or "Account"
        if a.get("is_overdue"):
            min_pay = int(a.get("min_payment_cents") or 0)
            due_day = a.get("due_day")
            bits: List[str] = []
            if min_pay > 0:
                bits.append(f"min payment {_fmt_usd(min_pay)}")
            if due_day:
                bits.append(f"due day {due_day}")
            detail = ", ".join(bits) if bits else None
            cards.append(
                make_card(
                    type="overdue_account",
                    severity="warn",
                    title="Account overdue",
                    summary=f"{name} is marked overdue",
                    detail=detail,
                    dedupe_key=f"overdue_account:{a.get('id')}",
                    action_url="/accounts",
                    action_label="Open accounts",
                )
            )

        if a.get("type") != "credit":
            continue
        limit = int(a.get("credit_limit_cents") or 0)
        bal = int(a.get("current_balance_cents") or 0)
        if limit <= 0 or bal <= 0:
            continue
        util = bal / limit
        if util > UTIL_WARN_THRESHOLD:
            severity = "warn"
        elif util > UTIL_INFO_THRESHOLD:
            severity = "info"
        else:
            continue
        cards.append(
            make_card(
                type="high_utilization",
                severity=severity,
                title="Credit-card utilization",
                summary=(
                    f"{name} {int(util * 100)}% utilized "
                    f"({_fmt_usd(bal)} / {_fmt_usd(limit)})"
                ),
                detail=(
                    "Keeping utilization under 30% is a meaningful boost to your credit score."
                    if severity == "warn"
                    else None
                ),
                dedupe_key=f"high_utilization:{a.get('id')}",
                action_url="/accounts",
                action_label="Open accounts",
            )
        )
    return cards
