"""Orchestrator for the Insights feed.

Delegates per-card construction to ``web.insights.cards`` and composes
the final payload. Shared data (category breakdown, recurring streams,
accounts, budget progress) is fetched **once** and reused across
builders to keep the feed O(1) repo calls rather than O(cards).
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from web.insights import cards as card_builders
from web.insights.cards import make_card

logger = logging.getLogger(__name__)


# ``liquidity_buffer`` thresholds. Warn when upcoming outflows in the next
# ``LIQUIDITY_BUFFER_DAYS`` days exceed ``LIQUIDITY_BUFFER_RATIO`` of the
# current liquid (depository) balances. Kept as module-level constants so
# the rule matches ``cards.BUDGET_RISK_RATIO`` and is easy to tune without
# hunting through the function body.
LIQUIDITY_BUFFER_RATIO = 0.40
LIQUIDITY_BUFFER_DAYS = 30


async def build_insights_feed(viewer_user_id: Optional[int] = None) -> Dict[str, Any]:
    from web.accounts.repo import AccountsRepository
    from web.budgets.repo import BudgetsRepository
    from web.reports.calculations import build_forecast, compute_health_score
    from web.recurring.repo import RecurringRepository
    from web.reports.repo import ReportsRepository

    today = date.today()
    month = today.strftime("%Y-%m")

    reports = ReportsRepository()
    recurring = RecurringRepository()
    accounts_repo = AccountsRepository()
    budgets_repo = BudgetsRepository()

    cards: List[Dict[str, Any]] = []

    # Shared data fetched once. Each block is wrapped so a single failure
    # doesn't sink the rest of the feed.
    streams: List[Dict[str, Any]] = []
    try:
        streams = await recurring.list_streams(
            direction="outflow", active_only=True, viewer_user_id=viewer_user_id
        )
    except Exception as exc:
        logger.warning("insights recurring streams: %s", exc)

    accounts: List[Dict[str, Any]] = []
    try:
        accounts = await accounts_repo.list_accounts(active_only=True)
    except Exception as exc:
        logger.warning("insights accounts: %s", exc)

    budget_progress: List[Dict[str, Any]] = []
    try:
        budget_progress = await budgets_repo.get_progress(
            month, viewer_user_id=viewer_user_id
        )
    except Exception as exc:
        logger.warning("insights budget progress: %s", exc)

    # ---- Financial health ------------------------------------------------
    try:
        fh = await reports.get_financial_health_data(viewer_user_id=viewer_user_id)
        score = compute_health_score(**fh)
        cards.append(
            make_card(
                type="financial_health",
                severity="info",
                title="Financial health",
                summary=f"Score {score['score']} — {score['label']}",
                detail=score.get("advice"),
                dedupe_key=f"financial_health:{month}",
                action_url="/reports?tab=health",
                action_label="Open health report",
            )
        )
    except Exception as exc:
        logger.warning("insights health: %s", exc)

    # ---- Cash flow MoM (equal MTD windows) ------------------------------
    try:
        cur_start = today.replace(day=1)
        cur_end = today
        prev_month_end = cur_start - timedelta(days=1)
        prev_start = prev_month_end.replace(day=1)
        prev_days_in_month = calendar.monthrange(prev_start.year, prev_start.month)[1]
        prev_end_day = min(today.day, prev_days_in_month)
        prev_end = prev_start.replace(day=prev_end_day)
        cur = await reports.get_cash_flow_window(
            cur_start, cur_end, viewer_user_id=viewer_user_id
        )
        prv = await reports.get_cash_flow_window(
            prev_start, prev_end, viewer_user_id=viewer_user_id
        )
        delta = cur["net_cents"] - prv["net_cents"]
        tone = "warn" if delta < 0 else "info"
        cards.append(
            make_card(
                type="cash_flow_mom",
                severity=tone,
                title="Cash flow vs last month",
                summary=(
                    f"Net {cur['net_cents'] / 100:.2f} USD MTD "
                    f"(vs {prv['net_cents'] / 100:.2f} USD same days last month)"
                ),
                detail=f"Change in net: {delta / 100:.2f} USD across {today.day} day(s)",
                dedupe_key=f"cash_flow_mom:{month}",
                action_url="/reports?tab=cashflow",
                action_label="Open cash flow",
            )
        )
    except Exception as exc:
        logger.warning("insights cash flow: %s", exc)

    # ---- Top category (refund-safe) -------------------------------------
    try:
        by_cat = await reports.get_by_category(
            month, viewer_user_id=viewer_user_id, rollup="primary"
        )
        positive = [c for c in by_cat if (c.get("amount_cents") or 0) > 0]
        if positive:
            top = max(positive, key=lambda x: x["amount_cents"])
            cat_id = top.get("category_id")
            action_url = "/reports?tab=expenses"
            if cat_id:
                action_url = f"/reports?tab=expenses&category={cat_id}"
            cards.append(
                make_card(
                    type="top_category",
                    severity="info",
                    title="Largest spending category",
                    summary=top.get("category_name") or "Category",
                    detail=f"{(top.get('amount_cents') or 0) / 100:.2f} USD this month",
                    dedupe_key=f"top_category:{month}:{cat_id or 'na'}",
                    action_url=action_url,
                    action_label="Drill into category",
                )
            )
    except Exception as exc:
        logger.warning("insights by category: %s", exc)

    # ---- Category trend (Phase 3) ---------------------------------------
    try:
        rolling = await reports.get_category_rolling(
            month, months=3, viewer_user_id=viewer_user_id
        )
        cards.extend(card_builders.build_category_trend(rolling, month=month))
    except Exception as exc:
        logger.warning("insights category trend: %s", exc)

    # ---- Forecast runway -------------------------------------------------
    try:
        entries = build_forecast(streams, days=14)
        if entries:
            n = len(entries)
            cards.append(
                make_card(
                    type="forecast",
                    severity="info",
                    title="Upcoming bills",
                    summary=f"{n} outflows in the next 14 days",
                    detail="Review Recurring for dates and amounts.",
                    dedupe_key=f"forecast:{today.isoformat()}",
                    action_url="/recurring",
                    action_label="View recurring",
                )
            )
    except Exception as exc:
        logger.warning("insights forecast: %s", exc)

    # ---- Liquidity buffer -----------------------------------------------
    # Warn when the next ``LIQUIDITY_BUFFER_DAYS`` days of outflows eat a
    # large share of current depository (cash + bank) balances. This used
    # to be a bespoke card rendered directly by the Dashboard; folding it
    # into the feed keeps alerts in one place and lets users dismiss /
    # snooze it like any other insight.
    try:
        nw = await reports.get_net_worth()
        liquid = int(nw.get("liquid_cents") or 0)
        if liquid > 0:
            longer_entries = build_forecast(streams, days=LIQUIDITY_BUFFER_DAYS)
            outflow_cents = sum(abs(int(e.get("amount_cents") or 0)) for e in longer_entries)
            if outflow_cents > liquid * LIQUIDITY_BUFFER_RATIO:
                pct = (outflow_cents / liquid) * 100 if liquid else 0
                cards.append(
                    make_card(
                        type="liquidity_buffer",
                        severity="warn",
                        title="Cash flow heads-up",
                        summary=(
                            f"Upcoming bills in the next {LIQUIDITY_BUFFER_DAYS} days "
                            f"are ~{pct:.0f}% of your cash & bank balances"
                        ),
                        detail=(
                            f"${outflow_cents / 100:,.0f} forecast outflow vs "
                            f"${liquid / 100:,.0f} liquid. Review the forecast "
                            "and recurring payments."
                        ),
                        dedupe_key=f"liquidity_buffer:{today.isoformat()}",
                        action_url="/recurring",
                        action_label="Review recurring",
                    )
                )
    except Exception as exc:
        logger.warning("insights liquidity_buffer: %s", exc)

    # ---- Missed recurring (Phase 3) -------------------------------------
    try:
        cards.extend(card_builders.build_missed_recurring(streams, today=today))
    except Exception as exc:
        logger.warning("insights missed_recurring: %s", exc)

    # ---- Duplicate subscriptions (Phase 3) ------------------------------
    try:
        cards.extend(card_builders.build_duplicate_subscription(streams))
    except Exception as exc:
        logger.warning("insights duplicate_subscription: %s", exc)

    # ---- Overdue + utilization (Phase 3) --------------------------------
    try:
        cards.extend(
            card_builders.build_overdue_and_utilization(
                accounts, viewer_user_id=viewer_user_id
            )
        )
    except Exception as exc:
        logger.warning("insights overdue/utilization: %s", exc)

    # ---- Budget risk (Phase 3) ------------------------------------------
    try:
        cards.extend(
            card_builders.build_budget_risk(budget_progress, month=month, today=today)
        )
    except Exception as exc:
        logger.warning("insights budget_risk: %s", exc)

    # ---- Recurring price-change heads-up / good news --------------------
    try:
        changed = await recurring.get_price_changes(viewer_user_id=viewer_user_id)
        good_items: List[Dict[str, Any]] = []
        warn_items: List[Dict[str, Any]] = []
        for s in changed:
            pct_raw = s.get("price_change_pct")
            if pct_raw is None:
                continue
            try:
                pct = float(pct_raw)
            except (TypeError, ValueError):
                continue
            if not pct:
                continue
            direction = s.get("direction") or "outflow"
            is_outflow = direction == "outflow"
            if (is_outflow and pct > 0) or (not is_outflow and pct < 0):
                warn_items.append({"stream": s, "pct": pct})
            else:
                good_items.append({"stream": s, "pct": pct})

        def _label(entry: Dict[str, Any]) -> str:
            s = entry["stream"]
            return card_builders._stream_label(s)

        def _ids_key(items: List[Dict[str, Any]]) -> str:
            ids = sorted(str(x["stream"].get("id")) for x in items if x["stream"].get("id"))
            return ",".join(ids) or "none"

        if warn_items:
            warn_items.sort(key=lambda x: abs(x["pct"]), reverse=True)
            top = warn_items[:3]
            summary = ", ".join(
                f"{_label(w)} {'+' if w['pct'] > 0 else '−'}{abs(w['pct']):.0f}%" for w in top
            )
            cards.append(
                make_card(
                    type="price_changes_warn",
                    severity="warn",
                    title="Recurring charges moved against you",
                    summary=summary,
                    detail=(
                        f"{len(warn_items)} stream"
                        f"{'s' if len(warn_items) != 1 else ''} crossed the 10% threshold."
                    ),
                    dedupe_key=f"price_changes_warn:{_ids_key(warn_items)}",
                    action_url="/recurring?sort=price_change",
                    action_label="Review recurring",
                )
            )

        if good_items:
            good_items.sort(key=lambda x: abs(x["pct"]), reverse=True)
            top = good_items[:3]
            summary = ", ".join(
                f"{_label(g)} {'+' if g['pct'] > 0 else '−'}{abs(g['pct']):.0f}%" for g in top
            )
            cards.append(
                make_card(
                    type="price_changes_good",
                    severity="info",
                    title="Good news on recurring",
                    summary=summary,
                    detail=(
                        f"{len(good_items)} stream"
                        f"{'s' if len(good_items) != 1 else ''} moved in your favour."
                    ),
                    dedupe_key=f"price_changes_good:{_ids_key(good_items)}",
                    action_url="/recurring?sort=price_change",
                    action_label="Review recurring",
                )
            )
    except Exception as exc:
        logger.warning("insights price changes: %s", exc)

    actionable = sum(1 for c in cards if c.get("severity") == "warn")
    new_count = actionable  # Phase 4 wires this up to first_seen_at.
    return {
        "cards": cards,
        "actionable_count": actionable,
        "new_count": new_count,
    }
