"""
Transaction classifier — the canonical decision logic for income / expense /
internal_transfer / uncategorized.

The rules live in ``classify_row`` in the priority order documented in
``docs/reports-math.md``:

1. Manual override (``manual_class_override`` set by the user).
2. Pair match cash ↔ debt (depository outflow paired with credit/loan inflow).
3. Pair match depository ↔ depository (classic Plaid TRANSFER_OUT/IN).
4. Name match (Zelle counterparty name in ``app_settings.internal_transfer_names``).
5. Income by category (``categories.is_income = TRUE`` AND ``amount_cents < 0``).
5.5. Orphan ``TRANSFER_IN`` on a depository account with negative amount —
    money genuinely arriving from a bank we don't track yet. Counts as
    income, not an expense refund.
6. Expense fallback (depository / credit / cash outflow that is not a transfer).
7. Uncategorized (investment/loan outflows that do not pair).

Everything else is just plumbing: the ``match_pairs`` SQL that finds
candidate pairs in one query, ``rescan_all`` that loops over untouched rows
and writes the results, and ``classify_one_on_insert`` for the hot path in
Plaid sync + cash POST.

Design notes:
- The classifier operates on already-persisted rows. We never look at Plaid
  raw payloads here; everything needed is on ``transactions`` + joined
  ``accounts`` + ``categories`` + ``app_settings.internal_transfer_names``.
- ``manual_class_override`` wins over everything to preserve user intent.
- The legacy ``is_internal_transfer_manual = TRUE`` sentinel is honored too:
  rows flipped by the old UI before the migration keep their class forever
  (mapped into ``manual_class_override`` during the one-time backfill).
- No psycopg2 — asyncpg only (see ``docs/architecture.md``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional, Sequence, Set

import asyncpg

from web.plaid.internal_transfer import (
    classify_internal_transfer,
    get_configured_names,
)

logger = logging.getLogger(__name__)


TransactionClass = Literal["income", "expense", "internal_transfer", "uncategorized"]

ALL_CLASSES: tuple[TransactionClass, ...] = (
    "income",
    "expense",
    "internal_transfer",
    "uncategorized",
)

# Plaid PFC primaries that the cash ↔ debt pair matcher considers as
# "outflow looks like a debt payment": the depository-side of a credit-card
# bill pay ends up tagged LOAN_PAYMENTS by Plaid, while savings-to-savings
# or zelle-to-self is TRANSFER_OUT. Other PFC values (FOOD_AND_DRINK etc.)
# are never pair-matched against credit/loan accounts — coincidental
# same-amount purchases stay expenses.
_CASH_DEBT_SOURCE_PFC: frozenset[str] = frozenset(
    {"LOAN_PAYMENTS", "TRANSFER_OUT"}
)

# Account types that carry real outflow money into expense aggregates. A
# row on an ``investment`` or ``loan`` account that did not pair stays
# uncategorized — users rarely need these counted, and forcing them into
# expense would introduce phantom spend when the holdings/liabilities feed
# is fresher than the transactions feed.
_SPENDABLE_ACCOUNT_TYPES: frozenset[str] = frozenset(
    {"depository", "credit", "other"}
)

_DEBT_ACCOUNT_TYPES: frozenset[str] = frozenset({"credit", "loan"})


@dataclass
class ClassificationStats:
    """Result of a batch rescan — small, easy to log / audit.

    ``by_class`` counts the new class distribution; ``changed`` is the
    number of rows whose class value actually flipped. The two are related
    but not identical: a re-scan that re-computes every row can report
    the same distribution while still having zero changes.
    """

    total: int = 0
    changed: int = 0
    by_class: Dict[str, int] = field(default_factory=dict)
    paired: int = 0

    def bump(self, cls: str) -> None:
        self.by_class[cls] = self.by_class.get(cls, 0) + 1


@dataclass
class RowView:
    """Thin projection of a ``transactions`` row + joins the classifier needs.

    Built once per rescan pass (via a single SELECT) to keep the Python side
    allocation-free. Intentionally mirrors column names 1:1 so the caller
    can feed an asyncpg Record straight in.
    """

    id: int
    amount_cents: int
    account_type: Optional[str]
    pfc_primary: Optional[str]
    merchant_name: Optional[str]
    name: Optional[str]
    counterparties: Any
    source: Optional[str]
    category_is_income: bool
    manual_class_override: Optional[str]
    legacy_is_internal_transfer_manual: bool
    legacy_is_internal_transfer: bool


def classify_row(
    row: RowView,
    *,
    paired_ids: Set[int],
    name_matches: Sequence[str],
) -> TransactionClass:
    """
    Decide a single row's class. Pure function — no I/O, no side effects.

    Args:
        row: ``RowView`` with the fields the rules consult.
        paired_ids: Transaction ids that ``match_pairs`` found a partner for.
            Membership → one of rules 2 or 3 fired, so the row is an
            internal transfer.
        name_matches: Normalized family-wide internal-transfer names.

    Rules 1–7 run top-down; the first match wins.
    """
    # Rule 1: explicit user override. Never second-guess the user.
    if row.manual_class_override in ALL_CLASSES:
        return row.manual_class_override  # type: ignore[return-value]

    # The legacy binary flag pre-dates ``manual_class_override``. When the
    # user had toggled "Internal transfer" on the transaction row in the old
    # UI, that choice still wins — the migration copies it into
    # ``manual_class_override``. We check the raw flag here too so fresh
    # rows imported between the code deploy and the migration still honor
    # user intent.
    if row.legacy_is_internal_transfer_manual and row.legacy_is_internal_transfer:
        return "internal_transfer"

    # Rules 2 + 3: any pair-matched row.
    if row.id in paired_ids:
        return "internal_transfer"

    # Rule 4: Zelle-style counterparty-name match. Only relevant for
    # TRANSFER_IN/OUT rows; ``classify_internal_transfer`` guards this
    # itself, so we don't need to pre-filter by pfc_primary.
    if classify_internal_transfer(
        pfc_primary=row.pfc_primary,
        merchant_name=row.merchant_name,
        name=row.name,
        counterparties=row.counterparties,
        normalized_names=name_matches,
    ):
        return "internal_transfer"

    # Rule 5: income by category flag. Sign must agree with Plaid's
    # convention (credit side of the ledger is negative).
    if row.category_is_income:
        if row.amount_cents < 0:
            return "income"
        # Category says "income" but the row is a debit. Most likely the
        # user miscategorized a refund or a transfer into INCOME. Dropping
        # it into ``uncategorized`` makes the inconsistency visible in
        # diagnostics instead of silently inflating either bucket.
        return "uncategorized"

    acct_type = (row.account_type or "").lower()

    # Rule 5.5: orphan incoming depository transfer.
    #
    # A ``TRANSFER_IN`` that survived rules 2–4 did not pair with an outflow
    # and did not name-match any family member. On a depository account with
    # the typical Plaid credit sign (amount_cents < 0) it reads as money
    # genuinely arriving from outside the tracked set — e.g. a wire from a
    # bank we haven't connected, a Zelle from a non-family sender without a
    # name hit, a refund issued via ACH. Falling through to Rule 6 would tag
    # it as an expense refund, polluting the expense bucket with income-like
    # inflow. Keeping it out of Rule 7 (uncategorized) ensures it still
    # shows up on the income side of the cash-flow identity. Positive-amount
    # TRANSFER_IN rows are unusual (Plaid sometimes posts them on the send
    # leg) and stay in the expense fallback.
    if (
        row.pfc_primary == "TRANSFER_IN"
        and row.amount_cents < 0
        and acct_type == "depository"
    ):
        return "income"

    # Rule 6: everything that looks spendable is an expense — even with a
    # negative sign (refunds), because refunds reduce the month's spend in
    # the same category they came from.
    if row.source == "cash" or acct_type in _SPENDABLE_ACCOUNT_TYPES:
        return "expense"

    # Rule 7: investment / loan rows that did not pair. These typically
    # reflect internal capital movements (401k inflow, mortgage principal
    # posted on a loan account) and are surfaced via the diagnostics
    # endpoint so power users can override them.
    return "uncategorized"


# ---------------------------------------------------------------------------
# Pair matching (SQL-heavy)
# ---------------------------------------------------------------------------


async def match_pairs(
    conn: asyncpg.Connection,
    *,
    horizon_days: Optional[int] = 90,
) -> Set[int]:
    """
    Find internal-transfer pairs across family accounts and return the set
    of transaction ids that should be classified as ``internal_transfer``.

    Three queries are combined (first two are cent-exact, third is a
    fee-tolerant fallback):

    1. **Cash ↔ debt (exact)** — the common credit-card-bill / loan-payment
       case. Source is an outflow (``amount > 0``) on a ``depository``
       account with ``pfc_primary IN ('LOAN_PAYMENTS', 'TRANSFER_OUT')``.
       Sink is the opposite sign on a ``credit`` or ``loan`` account
       within ±3 days. Both accounts must belong to the same family (any
       identifiable owner is enough).
    2. **Depository ↔ depository (exact)** — the classic Plaid
       TRANSFER_OUT / TRANSFER_IN pair (savings ↔ checking, PayPal →
       Chase …) with matching cents within ±3 days.
    3. **Depository ↔ depository (tolerant)** — same shape as #2 but the
       counterparties' amounts may differ by up to
       ``max(500¢, 1% of the outflow)`` and the date window is tighter
       (±1 day). Catches PayPal Instant Transfer fees, small wire fees
       and sub-dollar FX rounding where Plaid posts the net on one side.
       Runs **after** the exact matchers and **excludes** rows they
       already paired, so exact matches always win. Tie-breaking in
       ROW_NUMBER prefers the smallest amount delta first, then the
       smallest date delta, so an outflow with a fee-adjusted candidate
       and a cent-exact candidate still pairs with the cent-exact one.

    ``horizon_days=None`` scans the whole history; otherwise only rows
    within the last N days participate. ROW_NUMBER() dedupes candidates
    in every query so an outflow with two inflow candidates still pairs
    1:1.
    """
    if horizon_days is not None and horizon_days <= 0:
        return set()

    params: list = [horizon_days]

    cash_debt_rows = await conn.fetch(
        """
        WITH scoped AS (
          SELECT t.id, t.account_id, t.amount_cents, t.date,
                 t.pfc_primary,
                 a.type AS account_type,
                 COALESCE(a.user_id, p.user_id) AS owner_uid
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
          LEFT JOIN plaid_items p ON p.item_id = a.plaid_item_id
          WHERE t.source IN ('plaid', 'plaid_sandbox')
            AND t.is_internal_transfer_manual = FALSE
            AND ($1::int IS NULL OR t.date >= CURRENT_DATE - $1::int * INTERVAL '1 day')
        ),
        pairs AS (
          SELECT
            o.id AS out_id, i.id AS in_id,
            ROW_NUMBER() OVER (
              PARTITION BY o.id ORDER BY ABS(o.date - i.date), i.id
            ) AS rn_out,
            ROW_NUMBER() OVER (
              PARTITION BY i.id ORDER BY ABS(o.date - i.date), o.id
            ) AS rn_in
          FROM scoped o
          JOIN scoped i
            ON o.account_type = 'depository'
           AND o.amount_cents > 0
           AND o.pfc_primary IN ('LOAN_PAYMENTS', 'TRANSFER_OUT')
           AND i.account_type IN ('credit', 'loan')
           AND i.amount_cents = -o.amount_cents
           AND i.owner_uid IS NOT NULL
           AND o.owner_uid IS NOT NULL
           -- Both legs must belong to the SAME family member. Without this,
           -- a same-day same-amount coincidence between spouse A's
           -- depository outflow and spouse B's credit-card balance change
           -- would falsely pair → both rows vanish from income/expense
           -- reports. Cross-family transfers are handled by the Zelle name
           -- list (rule 4), which doesn't go through this matcher at all.
           AND o.owner_uid = i.owner_uid
           AND ABS(o.date - i.date) <= 3
        )
        SELECT out_id, in_id
        FROM pairs
        WHERE rn_out = 1 AND rn_in = 1
        """,
        *params,
    )

    depository_rows = await conn.fetch(
        """
        WITH scoped AS (
          SELECT t.id, t.account_id, t.amount_cents, t.date,
                 t.pfc_primary,
                 a.type AS account_type,
                 COALESCE(a.user_id, p.user_id) AS owner_uid
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
          LEFT JOIN plaid_items p ON p.item_id = a.plaid_item_id
          WHERE t.source IN ('plaid', 'plaid_sandbox')
            AND t.is_internal_transfer_manual = FALSE
            AND t.pfc_primary IN ('TRANSFER_IN', 'TRANSFER_OUT')
            AND ($1::int IS NULL OR t.date >= CURRENT_DATE - $1::int * INTERVAL '1 day')
        ),
        pairs AS (
          SELECT
            o.id AS out_id, i.id AS in_id,
            ROW_NUMBER() OVER (
              PARTITION BY o.id ORDER BY ABS(o.date - i.date), i.id
            ) AS rn_out,
            ROW_NUMBER() OVER (
              PARTITION BY i.id ORDER BY ABS(o.date - i.date), o.id
            ) AS rn_in
          FROM scoped o
          JOIN scoped i
            ON o.pfc_primary = 'TRANSFER_OUT'
           AND i.pfc_primary = 'TRANSFER_IN'
           AND i.account_id <> o.account_id
           AND i.owner_uid IS NOT NULL
           AND o.owner_uid IS NOT NULL
           -- Same-family-member guard. See cash↔debt matcher above for
           -- the full rationale; cross-spouse pairs would silently
           -- erase real income + real expense from the family reports.
           AND o.owner_uid = i.owner_uid
           AND i.amount_cents = -o.amount_cents
           AND o.amount_cents > 0
           AND o.account_type = 'depository'
           AND i.account_type = 'depository'
           AND ABS(o.date - i.date) <= 3
        )
        SELECT out_id, in_id
        FROM pairs
        WHERE rn_out = 1 AND rn_in = 1
        """,
        *params,
    )

    paired: Set[int] = set()
    for r in cash_debt_rows:
        paired.add(r["out_id"])
        paired.add(r["in_id"])
    for r in depository_rows:
        paired.add(r["out_id"])
        paired.add(r["in_id"])

    # Third pass: depository ↔ depository tolerance matcher. Covers fee-split
    # pairs like PayPal Instant Transfer (1.75% fee) and small wire / FX
    # rounding. Runs *after* the exact matchers and excludes rows they
    # already paired so cent-exact matches always win.
    tolerance_rows = await conn.fetch(
        """
        WITH scoped AS (
          SELECT t.id, t.account_id, t.amount_cents, t.date,
                 t.pfc_primary,
                 a.type AS account_type,
                 COALESCE(a.user_id, p.user_id) AS owner_uid
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
          LEFT JOIN plaid_items p ON p.item_id = a.plaid_item_id
          WHERE t.source IN ('plaid', 'plaid_sandbox')
            AND t.is_internal_transfer_manual = FALSE
            AND t.pfc_primary IN ('TRANSFER_IN', 'TRANSFER_OUT')
            AND NOT (t.id = ANY($2::int[]))
            AND ($1::int IS NULL OR t.date >= CURRENT_DATE - $1::int * INTERVAL '1 day')
        ),
        pairs AS (
          SELECT
            o.id AS out_id, i.id AS in_id,
            ROW_NUMBER() OVER (
              PARTITION BY o.id
              ORDER BY ABS(o.amount_cents + i.amount_cents), ABS(o.date - i.date), i.id
            ) AS rn_out,
            ROW_NUMBER() OVER (
              PARTITION BY i.id
              ORDER BY ABS(o.amount_cents + i.amount_cents), ABS(o.date - i.date), o.id
            ) AS rn_in
          FROM scoped o
          JOIN scoped i
            ON o.pfc_primary = 'TRANSFER_OUT'
           AND i.pfc_primary = 'TRANSFER_IN'
           AND i.account_id <> o.account_id
           AND i.owner_uid IS NOT NULL
           AND o.owner_uid IS NOT NULL
           -- Same-family-member guard. See cash↔debt matcher above for
           -- the full rationale; cross-spouse fee-tolerant pairs are
           -- the highest false-positive risk because the amount window
           -- is the loosest of the three queries.
           AND o.owner_uid = i.owner_uid
           AND o.amount_cents > 0
           AND i.amount_cents < 0
           AND o.account_type = 'depository'
           AND i.account_type = 'depository'
           -- Fee tolerance: max($25 floor, 2% of out) covers PayPal Instant
           -- Transfer for US personal accounts — 1.75% per leg, capped at
           -- $25 (https://www.paypal.com/us/digital-wallet/paypal-consumer-fees).
           -- The $25 floor matches PayPal's hard cap so a $10k transfer
           -- with the maximum $25 fee still pairs; the 2% ramp gives a
           -- 0.25% buffer above the headline rate for Plaid rounding and
           -- minor wire / FX deltas. The previous max($5, 1%) bound was
           -- off by 1.5× and missed every Instant Transfer above ~$285.
           AND ABS(o.amount_cents + i.amount_cents) <= GREATEST(2500, o.amount_cents * 2 / 100)
           AND ABS(o.amount_cents + i.amount_cents) > 0
           -- ±2 day window — PayPal IT lands same day or next business
           -- day; small ACH-with-fee can take two. Still tighter than the
           -- exact matcher's ±3 so cent-equality always wins.
           AND ABS(o.date - i.date) <= 2
        )
        SELECT out_id, in_id
        FROM pairs
        WHERE rn_out = 1 AND rn_in = 1
        """,
        horizon_days,
        list(paired),
    )
    for r in tolerance_rows:
        paired.add(r["out_id"])
        paired.add(r["in_id"])

    return paired


# ---------------------------------------------------------------------------
# Full rescan
# ---------------------------------------------------------------------------


_RESCAN_BATCH_SIZE = 5000


async def rescan_all(
    conn: asyncpg.Connection,
    *,
    horizon_days: Optional[int] = None,
) -> ClassificationStats:
    """
    Re-classify every eligible row and persist the result in
    ``transactions.transaction_class``. Manual-override rows are skipped
    so user intent is preserved. Returns a :class:`ClassificationStats`
    summary of the run.

    The implementation is intentionally straightforward: one SELECT to pull
    a batch of rows with the joins the classifier needs, one UPDATE per
    changed class. It runs in ``O(rows)`` and completes well under a
    minute for typical family history (~50k transactions).
    """
    normalized_names = await get_configured_names(conn)
    paired = await match_pairs(conn, horizon_days=horizon_days)

    params: list = []
    horizon_filter = ""
    if horizon_days is not None and horizon_days > 0:
        params.append(int(horizon_days))
        horizon_filter = (
            f" AND COALESCE(t.authorized_date, t.date) >= "
            f"CURRENT_DATE - ${len(params)}::int * INTERVAL '1 day'"
        )

    stats = ClassificationStats(paired=len(paired) // 2)
    last_id = 0
    while True:
        batch_params = [*params, last_id, _RESCAN_BATCH_SIZE]
        last_id_idx = len(params) + 1
        limit_idx = len(params) + 2
        rows = await conn.fetch(
            f"""
            SELECT
                t.id,
                t.amount_cents,
                t.pfc_primary,
                t.merchant_name,
                t.name,
                t.counterparties,
                t.source,
                t.manual_class_override,
                t.transaction_class,
                t.is_internal_transfer,
                t.is_internal_transfer_manual,
                a.type AS account_type,
                COALESCE(c.is_income, FALSE) AS category_is_income
            FROM transactions t
            LEFT JOIN accounts a ON a.id = t.account_id
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.id > ${last_id_idx}
              {horizon_filter}
            ORDER BY t.id
            LIMIT ${limit_idx}
            """,
            *batch_params,
        )
        if not rows:
            break
        updates: list[tuple[int, str]] = []
        for r in rows:
            view = RowView(
                id=r["id"],
                amount_cents=int(r["amount_cents"]),
                account_type=r["account_type"],
                pfc_primary=r["pfc_primary"],
                merchant_name=r["merchant_name"],
                name=r["name"],
                counterparties=r["counterparties"],
                source=r["source"],
                category_is_income=bool(r["category_is_income"]),
                manual_class_override=r["manual_class_override"],
                legacy_is_internal_transfer_manual=bool(
                    r["is_internal_transfer_manual"]
                ),
                legacy_is_internal_transfer=bool(r["is_internal_transfer"]),
            )
            new_cls = classify_row(
                view, paired_ids=paired, name_matches=normalized_names
            )
            stats.total += 1
            stats.bump(new_cls)
            if r["transaction_class"] != new_cls:
                updates.append((r["id"], new_cls))
        if updates:
            await conn.executemany(
                """
                UPDATE transactions SET
                    transaction_class    = $2,
                    is_internal_transfer = ($2 = 'internal_transfer'),
                    updated_at           = NOW()
                WHERE id = $1
                """,
                updates,
            )
            stats.changed += len(updates)
        last_id = rows[-1]["id"]
        if len(rows) < _RESCAN_BATCH_SIZE:
            break

    logger.info(
        "Classification rescan: total=%d changed=%d paired=%d by_class=%s",
        stats.total,
        stats.changed,
        stats.paired,
        stats.by_class,
    )
    return stats


# ---------------------------------------------------------------------------
# Hot-path helper for sync / cash POST
# ---------------------------------------------------------------------------


async def classify_one_on_insert(
    conn: asyncpg.Connection,
    transaction_id: int,
    *,
    name_matches: Optional[Sequence[str]] = None,
) -> TransactionClass:
    """
    Compute and persist the class for a single freshly-inserted row.

    We re-run the pair matcher only over a 7-day horizon (same as the
    inline call in ``PlaidRepository.import_transactions``) so a new
    TRANSFER_OUT that beats its sibling TRANSFER_IN by one sync cycle can
    still flip to internal as soon as the partner lands. The cost is one
    small query per insert; negligible against the Plaid API round-trip
    that dominates sync latency.
    """
    if name_matches is None:
        name_matches = await get_configured_names(conn)
    paired = await match_pairs(conn, horizon_days=7)

    row = await conn.fetchrow(
        """
        SELECT
            t.id,
            t.amount_cents,
            t.pfc_primary,
            t.merchant_name,
            t.name,
            t.counterparties,
            t.source,
            t.manual_class_override,
            t.is_internal_transfer,
            t.is_internal_transfer_manual,
            a.type AS account_type,
            COALESCE(c.is_income, FALSE) AS category_is_income
        FROM transactions t
        LEFT JOIN accounts a ON a.id = t.account_id
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.id = $1
        """,
        transaction_id,
    )
    if row is None:
        return "uncategorized"

    view = RowView(
        id=row["id"],
        amount_cents=int(row["amount_cents"]),
        account_type=row["account_type"],
        pfc_primary=row["pfc_primary"],
        merchant_name=row["merchant_name"],
        name=row["name"],
        counterparties=row["counterparties"],
        source=row["source"],
        category_is_income=bool(row["category_is_income"]),
        manual_class_override=row["manual_class_override"],
        legacy_is_internal_transfer_manual=bool(row["is_internal_transfer_manual"]),
        legacy_is_internal_transfer=bool(row["is_internal_transfer"]),
    )
    new_cls = classify_row(view, paired_ids=paired, name_matches=list(name_matches))
    await conn.execute(
        """
        UPDATE transactions SET
            transaction_class    = $2,
            is_internal_transfer = ($2 = 'internal_transfer'),
            updated_at           = NOW()
        WHERE id = $1
        """,
        transaction_id,
        new_cls,
    )
    return new_cls


__all__ = [
    "ALL_CLASSES",
    "ClassificationStats",
    "RowView",
    "TransactionClass",
    "classify_row",
    "classify_one_on_insert",
    "match_pairs",
    "rescan_all",
]
