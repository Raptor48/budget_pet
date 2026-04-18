"""Build the /api/insights/feed payload from existing report repositories (no N+1 HTTP)."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def build_insights_feed(viewer_user_id: Optional[int] = None) -> Dict[str, Any]:
    from web.reports.calculations import build_forecast, compute_health_score
    from web.reports.repo import ReportsRepository
    from web.recurring.repo import RecurringRepository

    cards: List[Dict[str, Any]] = []
    month = date.today().strftime("%Y-%m")
    prev = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    reports = ReportsRepository()
    recurring = RecurringRepository()

    # Financial health
    try:
        fh = await reports.get_financial_health_data(viewer_user_id=viewer_user_id)
        score = compute_health_score(**fh)
        cards.append(
            {
                "type": "financial_health",
                "severity": "info",
                "title": "Financial health",
                "summary": f"Score {score['score']} — {score['label']}",
                "detail": score.get("advice"),
            }
        )
    except Exception as exc:
        logger.warning("insights health: %s", exc)

    # Cash flow vs last month
    try:
        cur = await reports.get_cash_flow(month, viewer_user_id=viewer_user_id)
        prv = await reports.get_cash_flow(prev, viewer_user_id=viewer_user_id)
        delta = cur["net_cents"] - prv["net_cents"]
        tone = "warn" if delta < 0 else "info"
        cards.append(
            {
                "type": "cash_flow_mom",
                "severity": tone,
                "title": "Cash flow vs last month",
                "summary": f"Net this month {cur['net_cents'] / 100:.2f} USD vs prior month",
                "detail": f"Change in net: {delta / 100:.2f} USD",
            }
        )
    except Exception as exc:
        logger.warning("insights cash flow: %s", exc)

    # Top category spend shift (simple: max category share message)
    try:
        by_cat = await reports.get_by_category(
            month, viewer_user_id=viewer_user_id, rollup="primary"
        )
        if by_cat:
            top = max(by_cat, key=lambda x: x.get("amount_cents", 0) or 0)
            cards.append(
                {
                    "type": "top_category",
                    "severity": "info",
                    "title": "Largest spending category",
                    "summary": top.get("category_name") or "Category",
                    "detail": f"{(top.get('amount_cents') or 0) / 100:.2f} USD this month",
                }
            )
    except Exception as exc:
        logger.warning("insights by category: %s", exc)

    # Forecast runway hint
    try:
        streams = await recurring.list_streams(direction="outflow", active_only=True)
        entries = build_forecast(streams, days=14)
        if entries:
            n = len(entries)
            cards.append(
                {
                    "type": "forecast",
                    "severity": "info",
                    "title": "Upcoming bills",
                    "summary": f"{n} outflows in the next 14 days",
                    "detail": "Review Recurring for dates and amounts.",
                }
            )
    except Exception as exc:
        logger.warning("insights forecast: %s", exc)

    # Recurring price-change heads-up / good news
    # -----------------------------------------------------------------
    # `price_change_pct` is signed (see web/recurring/repo.py). We classify
    # movement against stream direction to turn it into user-perceived good
    # news (price drop on a subscription) or a warning (price hike).
    try:
        changed = await recurring.get_price_changes()
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
            # Positive pct = last > avg (more expensive). Outflows warn on +,
            # inflows warn on -.
            if (is_outflow and pct > 0) or (not is_outflow and pct < 0):
                warn_items.append({"stream": s, "pct": pct})
            else:
                good_items.append({"stream": s, "pct": pct})

        def _label(entry: Dict[str, Any]) -> str:
            s = entry["stream"]
            return (
                (s.get("user_label") or "").strip()
                or s.get("display_title")
                or s.get("merchant_name")
                or s.get("description")
                or "Subscription"
            )

        if warn_items:
            warn_items.sort(key=lambda x: abs(x["pct"]), reverse=True)
            top = warn_items[:3]
            summary = ", ".join(
                f"{_label(w)} {'+' if w['pct'] > 0 else '−'}{abs(w['pct']):.0f}%"
                for w in top
            )
            cards.append(
                {
                    "type": "price_changes_warn",
                    "severity": "warn",
                    "title": "Recurring charges moved against you",
                    "summary": summary,
                    "detail": (
                        f"{len(warn_items)} stream"
                        f"{'s' if len(warn_items) != 1 else ''} crossed the 10% threshold."
                    ),
                }
            )

        if good_items:
            good_items.sort(key=lambda x: abs(x["pct"]), reverse=True)
            top = good_items[:3]
            summary = ", ".join(
                f"{_label(g)} {'+' if g['pct'] > 0 else '−'}{abs(g['pct']):.0f}%"
                for g in top
            )
            cards.append(
                {
                    "type": "price_changes_good",
                    "severity": "info",
                    "title": "Good news on recurring",
                    "summary": summary,
                    "detail": (
                        f"{len(good_items)} stream"
                        f"{'s' if len(good_items) != 1 else ''} moved in your favour."
                    ),
                }
            )
    except Exception as exc:
        logger.warning("insights price changes: %s", exc)

    actionable = sum(1 for c in cards if c.get("severity") == "warn")
    return {"cards": cards, "actionable_count": actionable}
