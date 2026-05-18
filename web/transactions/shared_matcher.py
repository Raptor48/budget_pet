"""
Auto-matcher for shared-expense reimbursements.

When the user splits a Travel transaction as ``$50 mine + $150 Shared``,
the $150 sits in the Shared (receivable) category as an outstanding
balance. When a friend Zelles $150 back a few days later, Plaid imports
that as a generic income transaction. Without help it stays mis-classified
as income.

This matcher closes the loop: it scans recent inflows and, when it can
prove a Zelle/cash inflow is the settlement of an outstanding receivable
with high confidence, re-categorises the inflow into Shared so the math
nets to zero. The UI shows a ``🔗 matched`` chip on the row so the user
can see (and one-click undo) the auto-assignment.

Decision rule (deliberately conservative — never auto-match when in doubt):

* Window: lookback ``BOT_SHARED_MATCH_WINDOW_DAYS`` (default 4) days from
  the inflow's date. Covers typical Zelle/Venmo settlement lag.

* Amount: exact cents match. No fuzzy matching — a $150 receivable does
  NOT auto-match a $149.50 inflow. Users almost always Venmo the exact
  amount; partial matches breed false positives.

* Uniqueness: ``outstanding_count = (receivable splits at amount X) -
  (already-categorised receivable inflows at amount X)`` over the window.
  Auto-match only when this count is **exactly 1**. Zero ⇒ no recent
  receivable to settle, leave alone. ≥2 ⇒ ambiguous, leave for the user
  to disambiguate manually (we'd rather miss a match than fabricate one).

Idempotency: transactions already categorised Shared are skipped. The
scan can be re-run after every Plaid sync without double-touching rows.

The matcher does NOT formally link inflow ↔ outflow rows. Settlement is
balance-based: SUM over the Shared category nets to zero when fully
settled. Per-person tracking lives in ``transaction_splits.counterparty``
which the matcher copies from the matched outflow split when set.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any, Dict, List, Optional

from web.db import get_pool

logger = logging.getLogger(__name__)


def _window_days() -> int:
    """Lookback days for auto-match. Env-tunable so we can lengthen the
    window without a redeploy if real Zelle lag turns out higher than 4."""
    try:
        raw = int(os.getenv("BOT_SHARED_MATCH_WINDOW_DAYS", "4"))
    except ValueError:
        raw = 4
    # Clamp to a sane range — a 0-day window matches nothing, a 60-day
    # window would auto-match wholly unrelated payments.
    return max(1, min(raw, 30))


async def _shared_category_id(conn) -> Optional[int]:
    """The single seeded Shared row's id. Cached implicitly via Postgres
    plan cache; we re-fetch each pass so the lookup tolerates a manual
    rename / re-seed in dev."""
    return await conn.fetchval(
        "SELECT id FROM categories WHERE is_receivable = TRUE ORDER BY id LIMIT 1"
    )


async def _list_unrouted_inflows(
    conn, *, shared_category_id: int, lookback_days: int
) -> List[Dict[str, Any]]:
    """Inflow transactions in the window that are NOT yet Shared.

    Class predicate is ``income`` because Zelle / Venmo / cash refunds
    all land as income before they're auto-matched. We deliberately do
    NOT scan transactions whose category is already Shared (skipping
    already-matched rows = the idempotency guarantee).
    """
    rows = await conn.fetch(
        """
        SELECT t.id,
               t.account_id,
               t.amount_cents,
               COALESCE(t.authorized_date, t.date) AS effective_date,
               t.merchant_name
        FROM transactions t
        WHERE t.transaction_class = 'income'
          AND t.amount_cents < 0
          AND COALESCE(t.authorized_date, t.date)
              >= (CURRENT_DATE - ($1 || ' days')::interval)
          AND COALESCE(t.category_id, 0) <> $2
        ORDER BY effective_date DESC, t.id DESC
        """,
        int(lookback_days),
        int(shared_category_id),
    )
    return [dict(r) for r in rows]


async def _outstanding_count_at(
    conn,
    *,
    amount_cents_abs: int,
    effective_date,
    lookback_days: int,
    exclude_inflow_id: int,
) -> int:
    """Number of un-settled receivables at this exact amount in the window.

    Outstanding = receivable splits at +amount minus already-categorised
    receivable inflows at -amount. We exclude the inflow we're
    evaluating so we don't count it against itself.

    The window straddles ``[effective_date - lookback, effective_date + lookback]``
    SYMMETRICALLY. Pre-payment is a real case — a friend Venmos you a
    day before the trip's transit charge actually posts, and a one-sided
    lookback would silently miss it. Same span used for both legs of
    the balance.
    """
    row = await conn.fetchrow(
        """
        WITH outflow_splits AS (
            SELECT COUNT(*) AS n
            FROM transaction_splits ts
            JOIN categories c ON c.id = ts.category_id
            JOIN transactions t ON t.id = ts.parent_transaction_id
            WHERE c.is_receivable = TRUE
              AND ts.amount_cents = $1
              AND COALESCE(t.authorized_date, t.date)
                  BETWEEN ($2::date - ($3 || ' days')::interval)
                      AND ($2::date + ($3 || ' days')::interval)
        ),
        already_matched_inflows AS (
            SELECT COUNT(*) AS n
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE c.is_receivable = TRUE
              AND t.amount_cents = -$1
              AND t.id <> $4
              AND COALESCE(t.authorized_date, t.date)
                  BETWEEN ($2::date - ($3 || ' days')::interval)
                      AND ($2::date + ($3 || ' days')::interval)
        )
        SELECT
            (SELECT n FROM outflow_splits)
          - (SELECT n FROM already_matched_inflows) AS outstanding
        """,
        int(amount_cents_abs),
        effective_date,
        int(lookback_days),
        int(exclude_inflow_id),
    )
    return int(row["outstanding"]) if row else 0


async def _matched_counterparty(
    conn,
    *,
    amount_cents_abs: int,
    effective_date,
    lookback_days: int,
) -> Optional[str]:
    """When the matcher finds a single outstanding receivable, copy that
    split's ``counterparty`` onto the inflow if it was set. Returns NULL
    when no candidate has counterparty filled — that's fine, the inflow
    just gets matched without a per-person tag.

    If multiple candidate splits have *different* non-null counterparties,
    return NULL (can't pick a winner deterministically).
    """
    rows = await conn.fetch(
        """
        SELECT DISTINCT ts.counterparty
        FROM transaction_splits ts
        JOIN categories c ON c.id = ts.category_id
        JOIN transactions t ON t.id = ts.parent_transaction_id
        WHERE c.is_receivable = TRUE
          AND ts.amount_cents = $1
          AND ts.counterparty IS NOT NULL
          AND COALESCE(t.authorized_date, t.date)
              BETWEEN ($2::date - ($3 || ' days')::interval)
                  AND ($2::date + ($3 || ' days')::interval)
        """,
        int(amount_cents_abs),
        effective_date,
        int(lookback_days),
    )
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]["counterparty"]
    # Multiple distinct counterparties — ambiguous, leave the auto-tag off.
    return None


async def _assign_to_shared(
    conn,
    *,
    transaction_id: int,
    shared_category_id: int,
    counterparty: Optional[str],
) -> None:
    """Re-categorise the inflow as Shared and stamp ``auto_matched_at``
    on its (new) split row. Stamped on the SPLIT, not the transaction,
    because the UI plashka is per-split (a future feature could split an
    inflow across multiple receivables — same shape).

    Implementation: the inflow has no splits in the unrouted state
    (auto-matched inflows are whole-row Shared). We set the parent
    category to Shared so the standard category-based aggregations pick
    up the right exclusion. The ``auto_matched_at`` chip in the UI is
    driven by a virtual lookup ("category is Shared and was set within
    the last few minutes by the matcher") — see TransactionOut.

    Conceptually cleaner: insert a single auto-split with
    counterparty + auto_matched_at, but that breaks the splits invariant
    (split sum must equal parent total) only if the parent has multiple
    splits; a single split equalling the parent is fine. We use the
    single-split form because (a) it lets ``counterparty`` and
    ``auto_matched_at`` live on the row that has the metadata columns,
    (b) keeps the UX symmetric with manually-created Shared splits.
    """
    async with conn.transaction():
        await conn.execute(
            "UPDATE transactions SET category_id = $2, updated_at = NOW() WHERE id = $1",
            int(transaction_id),
            int(shared_category_id),
        )
        # Defensive: if splits already exist on this row (shouldn't, but
        # the unrouted check above is liberal), don't double-insert.
        existing = await conn.fetchval(
            "SELECT 1 FROM transaction_splits WHERE parent_transaction_id = $1 LIMIT 1",
            int(transaction_id),
        )
        if existing is not None:
            return
        amount = await conn.fetchval(
            "SELECT amount_cents FROM transactions WHERE id = $1", int(transaction_id)
        )
        if amount is None:
            return
        await conn.execute(
            """
            INSERT INTO transaction_splits
                (parent_transaction_id, category_id, amount_cents,
                 counterparty, auto_matched_at)
            VALUES ($1, $2, $3, $4, NOW())
            """,
            int(transaction_id),
            int(shared_category_id),
            int(amount),
            counterparty,
        )


async def try_match_recent_inflows(*, lookback_days: Optional[int] = None) -> Dict[str, int]:
    """One pass of the auto-matcher. Returns counters for telemetry.

    Counters:
      * ``checked``    — unrouted inflows scanned
      * ``matched``    — newly assigned to the Shared category
      * ``ambiguous``  — outstanding count ≥ 2; user must disambiguate
      * ``no_match``   — no outstanding receivable at that amount in window
    """
    window = lookback_days if lookback_days is not None else _window_days()
    counters = {"checked": 0, "matched": 0, "ambiguous": 0, "no_match": 0}
    pool = await get_pool()
    async with pool.acquire() as conn:
        shared_id = await _shared_category_id(conn)
        if shared_id is None:
            logger.warning(
                "Shared category not seeded; auto-matcher is a no-op until migration applies."
            )
            return counters
        inflows = await _list_unrouted_inflows(
            conn, shared_category_id=shared_id, lookback_days=window
        )
        for inflow in inflows:
            counters["checked"] += 1
            amount_abs = abs(int(inflow["amount_cents"]))
            outstanding = await _outstanding_count_at(
                conn,
                amount_cents_abs=amount_abs,
                effective_date=inflow["effective_date"],
                lookback_days=window,
                exclude_inflow_id=int(inflow["id"]),
            )
            if outstanding == 1:
                counterparty = await _matched_counterparty(
                    conn,
                    amount_cents_abs=amount_abs,
                    effective_date=inflow["effective_date"],
                    lookback_days=window,
                )
                await _assign_to_shared(
                    conn,
                    transaction_id=int(inflow["id"]),
                    shared_category_id=int(shared_id),
                    counterparty=counterparty,
                )
                counters["matched"] += 1
            elif outstanding > 1:
                counters["ambiguous"] += 1
            else:
                counters["no_match"] += 1
    logger.info(
        "Shared auto-matcher: checked=%d matched=%d ambiguous=%d no_match=%d (window=%dd)",
        counters["checked"], counters["matched"],
        counters["ambiguous"], counters["no_match"], window,
    )
    return counters


# Helper alias for tests / docs:
_ = timedelta  # silence unused-import on future windowing helpers
