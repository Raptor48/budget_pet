"""
ReportsRepository — DB queries for all report endpoints + net worth snapshots.

All income/expense/internal-transfer aggregates read from the canonical
``transactions.transaction_class`` column. See ``docs/reports-math.md`` for
the classification rules and invariants; if this file and that doc ever
disagree, the doc is the source of truth and this file is buggy.

Key conventions used throughout:

- Expense totals use ``SUM(t.amount_cents)``, never ``SUM(CASE WHEN amount>0)``.
  This lets refunds (``amount_cents < 0`` on class='expense') naturally
  reduce the monthly total — the accountant-correct behavior.
- Income totals use ``SUM(-t.amount_cents)`` so the number surfaces as a
  positive user-facing amount (income arrives with negative cents per
  Plaid convention).
- Internal transfers are excluded from both income and expense by the class
  predicate itself. No ``NOT is_internal_transfer`` clause is needed.
"""
import logging
from datetime import date
from typing import Any, Dict, List, Literal, Optional

from web.db import get_pool
from web.env_flags import reports_include_plaid_sandbox
from web.merchant_rules.aliases import alias_join_sql

logger = logging.getLogger(__name__)


def _sandbox_tx_filter(alias: str = "t") -> str:
    if reports_include_plaid_sandbox():
        return ""
    return f" AND ({alias}.source IS NULL OR {alias}.source <> 'plaid_sandbox')"


def _sandbox_tx_filter_no_alias() -> str:
    if reports_include_plaid_sandbox():
        return ""
    return " AND (source IS NULL OR source <> 'plaid_sandbox')"


def _private_tx_filter_with_idx(alias: str, idx: int) -> str:
    """Return SQL fragment using asyncpg-style $N placeholder."""
    prefix = f"{alias}." if alias else ""
    return (
        f" AND (NOT {prefix}is_private OR EXISTS ("
        f"SELECT 1 FROM accounts _pa WHERE _pa.id = {prefix}account_id AND _pa.user_id = ${idx}))"
    )


def _income_predicate(alias: str = "t") -> str:
    """
    Canonical SQL predicate for "transaction is income".

    Thin wrapper around ``transaction_class = 'income'`` kept for callsite
    clarity. Every income aggregate (Cash Flow, Income tab, Financial
    Health) goes through this helper so changes to the definition
    happen in one place.
    """
    prefix = f"{alias}." if alias else ""
    return f"{prefix}transaction_class = 'income'"


def _expense_predicate(alias: str = "t") -> str:
    """Canonical predicate for "transaction is an expense". Symmetric to ``_income_predicate``."""
    prefix = f"{alias}." if alias else ""
    return f"{prefix}transaction_class = 'expense'"


def _internal_transfer_predicate(alias: str = "t") -> str:
    """Canonical predicate for "transaction is an internal transfer"."""
    prefix = f"{alias}." if alias else ""
    return f"{prefix}transaction_class = 'internal_transfer'"


# Retained for backwards compatibility with imports/tests that still reference
# the old helper. The new code paths use ``_expense_predicate`` instead.
def _not_internal_transfer(alias: str = "t") -> str:
    prefix = f"{alias}." if alias else ""
    return f"{prefix}transaction_class <> 'internal_transfer'"


class ReportsRepository:
    async def _pool(self):
        return await get_pool()

    async def get_cash_flow(self, month: str, viewer_user_id: Optional[int] = None) -> Dict[str, Any]:
        """Monthly income + expenses + internal transfer totals.

        Returns ``internal_transfer_cents`` alongside income and expenses so
        the UI can reassure the user that, e.g., a $1,200 CC payment is
        recognized as a movement between their own accounts rather than
        silently dropped.
        """
        pool = await self._pool()
        private_filter = (
            _private_tx_filter_with_idx("t", 2) if viewer_user_id is not None else ""
        )
        params: list = [month]
        if viewer_user_id is not None:
            params.append(viewer_user_id)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT
                    COALESCE(SUM(CASE WHEN {_income_predicate("t")} THEN -t.amount_cents ELSE 0 END), 0) AS income_cents,
                    COALESCE(SUM(CASE WHEN {_expense_predicate("t")} THEN t.amount_cents ELSE 0 END), 0) AS expenses_cents,
                    COALESCE(SUM(CASE WHEN {_internal_transfer_predicate("t")} THEN t.amount_cents ELSE 0 END), 0) AS internal_transfer_cents
                FROM transactions t
                WHERE COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                  AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                  {_sandbox_tx_filter("t")}
                  {private_filter}
                """,
                *params,
            )
        income = int(row["income_cents"] or 0)
        expenses = int(row["expenses_cents"] or 0)
        internal = int(row["internal_transfer_cents"] or 0)
        return {
            "month": month,
            "income_cents": income,
            "expenses_cents": expenses,
            "internal_transfer_cents": internal,
            "net_cents": income - expenses,
        }

    async def get_cash_flow_window(
        self,
        start_date: date,
        end_date: date,
        viewer_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Cash-flow totals for an arbitrary ``[start_date, end_date]`` window.

        Used by Insights to compare current month-to-date against the same
        MTD window of the previous month, so the delta isn't distorted by
        comparing a partial month to a full prior month.

        End date is **inclusive** (``<= end_date``).
        """
        pool = await self._pool()
        private_filter = (
            _private_tx_filter_with_idx("t", 3) if viewer_user_id is not None else ""
        )
        params: list = [start_date, end_date]
        if viewer_user_id is not None:
            params.append(viewer_user_id)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT
                    COALESCE(SUM(CASE WHEN {_income_predicate("t")} THEN -t.amount_cents ELSE 0 END), 0) AS income_cents,
                    COALESCE(SUM(CASE WHEN {_expense_predicate("t")} THEN t.amount_cents ELSE 0 END), 0) AS expenses_cents,
                    COALESCE(SUM(CASE WHEN {_internal_transfer_predicate("t")} THEN t.amount_cents ELSE 0 END), 0) AS internal_transfer_cents
                FROM transactions t
                WHERE COALESCE(t.authorized_date, t.date) >= $1
                  AND COALESCE(t.authorized_date, t.date) <= $2
                  {_sandbox_tx_filter("t")}
                  {private_filter}
                """,
                *params,
            )
        income = int(row["income_cents"] or 0)
        expenses = int(row["expenses_cents"] or 0)
        internal = int(row["internal_transfer_cents"] or 0)
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "income_cents": income,
            "expenses_cents": expenses,
            "internal_transfer_cents": internal,
            "net_cents": income - expenses,
        }

    async def get_cash_flow_history(self, months: int = 12, viewer_user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        pool = await self._pool()
        private_filter = (
            _private_tx_filter_with_idx("t", 2) if viewer_user_id is not None else ""
        )
        params: list = [months]
        if viewer_user_id is not None:
            params.append(viewer_user_id)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    TO_CHAR(COALESCE(t.authorized_date, t.date), 'YYYY-MM') AS month,
                    COALESCE(SUM(CASE WHEN {_income_predicate("t")} THEN -t.amount_cents ELSE 0 END), 0) AS income_cents,
                    COALESCE(SUM(CASE WHEN {_expense_predicate("t")} THEN t.amount_cents ELSE 0 END), 0) AS expenses_cents,
                    COALESCE(SUM(CASE WHEN {_internal_transfer_predicate("t")} THEN t.amount_cents ELSE 0 END), 0) AS internal_transfer_cents
                FROM transactions t
                WHERE COALESCE(t.authorized_date, t.date) >= (CURRENT_DATE - INTERVAL '1 month' * $1)::date
                  {_sandbox_tx_filter("t")}
                  {private_filter}
                GROUP BY month
                ORDER BY month DESC
                """,
                *params,
            )
        result = []
        for r in rows:
            income = int(r["income_cents"] or 0)
            expenses = int(r["expenses_cents"] or 0)
            internal = int(r["internal_transfer_cents"] or 0)
            result.append({
                "month": r["month"],
                "income_cents": income,
                "expenses_cents": expenses,
                "internal_transfer_cents": internal,
                "net_cents": income - expenses,
            })
        return result

    async def get_category_rolling(
        self,
        current_month: str,
        months: int = 3,
        viewer_user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return per-primary-category current-month spend and prior-N-month average.

        Rolled up to the primary category (``COALESCE(parent_id, id)``) so the
        result lines up with ``get_by_category(rollup='primary')``.

        Used by the ``category_trend`` insight card to detect MoM spikes.

        Output rows: ``{category_id, category_name, current_cents, avg_cents}``.
        ``avg_cents`` averages only **completed** months preceding
        ``current_month`` (clamped by the ``months`` parameter). If fewer
        months of history exist, the average is over whatever is present.
        """
        pool = await self._pool()
        private_filter = (
            _private_tx_filter_with_idx("t", 3) if viewer_user_id is not None else ""
        )
        params: list = [current_month, int(months)]
        if viewer_user_id is not None:
            params.append(viewer_user_id)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                WITH per_cat AS (
                    SELECT
                        COALESCE(c.parent_id, t.category_id) AS bucket_id,
                        TO_CHAR(COALESCE(t.authorized_date, t.date), 'YYYY-MM') AS m,
                        SUM(t.amount_cents) AS total_cents
                    FROM transactions t
                    LEFT JOIN categories c ON c.id = t.category_id
                    WHERE {_expense_predicate("t")}
                      AND COALESCE(t.authorized_date, t.date) >= (($1 || '-01')::date - (INTERVAL '1 month' * $2))
                      AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                      AND t.category_id IS NOT NULL
                      AND NOT EXISTS (SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id)
                      {_sandbox_tx_filter("t")}
                      {private_filter}
                    GROUP BY bucket_id, m

                    UNION ALL

                    SELECT
                        COALESCE(c.parent_id, ts.category_id) AS bucket_id,
                        TO_CHAR(COALESCE(t.authorized_date, t.date), 'YYYY-MM') AS m,
                        SUM(ts.amount_cents) AS total_cents
                    FROM transaction_splits ts
                    JOIN transactions t ON t.id = ts.parent_transaction_id
                    LEFT JOIN categories c ON c.id = ts.category_id
                    WHERE {_expense_predicate("t")}
                      AND COALESCE(t.authorized_date, t.date) >= (($1 || '-01')::date - (INTERVAL '1 month' * $2))
                      AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                      AND ts.category_id IS NOT NULL
                      {_sandbox_tx_filter("t")}
                      {private_filter}
                    GROUP BY bucket_id, m
                ),
                folded AS (
                    SELECT bucket_id, m, SUM(total_cents) AS total_cents
                    FROM per_cat
                    GROUP BY bucket_id, m
                )
                SELECT
                    f.bucket_id AS category_id,
                    cb.name AS category_name,
                    COALESCE(SUM(CASE WHEN f.m = $1 THEN f.total_cents ELSE 0 END), 0) AS current_cents,
                    COALESCE(AVG(CASE WHEN f.m < $1 THEN f.total_cents END), 0) AS avg_cents,
                    COUNT(DISTINCT CASE WHEN f.m < $1 THEN f.m END) AS prior_months
                FROM folded f
                LEFT JOIN categories cb ON cb.id = f.bucket_id
                GROUP BY f.bucket_id, cb.name
                ORDER BY current_cents DESC
                """,
                *params,
            )
        return [
            {
                "category_id": r["category_id"],
                "category_name": r["category_name"],
                "current_cents": int(r["current_cents"] or 0),
                "avg_cents": int(r["avg_cents"] or 0),
                "prior_months": int(r["prior_months"] or 0),
            }
            for r in rows
        ]

    async def get_by_category(
        self,
        month: str,
        viewer_user_id: Optional[int] = None,
        rollup: Literal["primary", "detailed"] = "primary",
        parent_category_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Aggregate expense spending by category for a month.

        Uses ``transaction_class = 'expense'`` + ``SUM(amount_cents)`` so
        refunds reduce the category they came from — the accountant-correct
        behavior. Internal transfers are excluded by the class predicate;
        no explicit ``is_internal_transfer`` filter is needed.

        rollup='primary' (default): group detailed children into their parent
            buckets so charts show ~10–15 meaningful slices instead of 40+.
            `bucket_key='p:<id>'` and `children_count` reflects how many
            detailed categories contributed to the bucket.
        rollup='detailed': return one row per detailed category.
            When `parent_category_id` is provided, scope to children of that
            parent (including direct hits on the parent row itself).
        """
        pool = await self._pool()
        private_filter = (
            _private_tx_filter_with_idx("t", 2) if viewer_user_id is not None else ""
        )
        params: list = [month]
        idx = 2
        if viewer_user_id is not None:
            params.append(viewer_user_id)
            idx += 1

        parent_filter_txn = ""
        parent_filter_split = ""
        if rollup == "detailed" and parent_category_id is not None:
            params.append(parent_category_id)
            parent_filter_txn = (
                f" AND (t.category_id = ${idx} "
                f"OR t.category_id IN (SELECT id FROM categories WHERE parent_id = ${idx}))"
            )
            parent_filter_split = (
                f" AND (ts.category_id = ${idx} "
                f"OR ts.category_id IN (SELECT id FROM categories WHERE parent_id = ${idx}))"
            )
            idx += 1

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                WITH actual AS (
                    SELECT t.category_id, SUM(t.amount_cents) AS amount_cents
                    FROM transactions t
                    WHERE {_expense_predicate("t")}
                      AND COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                      AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                      AND NOT EXISTS (SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id)
                      {_sandbox_tx_filter("t")}
                      {private_filter}
                      {parent_filter_txn}
                    GROUP BY t.category_id

                    UNION ALL

                    SELECT ts.category_id, SUM(ts.amount_cents)
                    FROM transaction_splits ts
                    JOIN transactions t ON t.id = ts.parent_transaction_id
                    WHERE {_expense_predicate("t")}
                      AND COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                      AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                      {_sandbox_tx_filter("t")}
                      {private_filter}
                      {parent_filter_split}
                    GROUP BY ts.category_id
                ),
                actual_enriched AS (
                    SELECT
                        a.category_id,
                        a.amount_cents,
                        c.parent_id,
                        c.name AS self_name,
                        c.color AS self_color
                    FROM actual a
                    LEFT JOIN categories c ON c.id = a.category_id
                )
                """
                + (
                    """,
                agg AS (
                    SELECT
                        COALESCE(parent_id, category_id) AS bucket_id,
                        SUM(amount_cents) AS amount_cents,
                        COUNT(DISTINCT CASE WHEN parent_id IS NOT NULL THEN category_id END) AS child_hits
                    FROM actual_enriched
                    GROUP BY COALESCE(parent_id, category_id)
                ),
                total AS (SELECT SUM(amount_cents) AS total FROM agg)
                SELECT
                    agg.bucket_id AS category_id,
                    COALESCE(c.name, 'Uncategorized') AS category_name,
                    agg.amount_cents,
                    CASE WHEN total.total > 0 THEN ROUND(agg.amount_cents::numeric / total.total * 100, 1) ELSE 0 END AS percent,
                    c.color AS color,
                    'p:' || COALESCE(agg.bucket_id::text, 'null') AS bucket_key,
                    c.parent_id AS parent_category_id,
                    COALESCE(agg.child_hits, 0)::int AS children_count
                FROM agg
                CROSS JOIN total
                LEFT JOIN categories c ON c.id = agg.bucket_id
                ORDER BY agg.amount_cents DESC
                """
                    if rollup == "primary"
                    else """,
                agg AS (
                    SELECT category_id, SUM(amount_cents) AS amount_cents
                    FROM actual_enriched
                    GROUP BY category_id
                ),
                total AS (SELECT SUM(amount_cents) AS total FROM agg)
                SELECT
                    agg.category_id,
                    COALESCE(c.name, 'Uncategorized') AS category_name,
                    agg.amount_cents,
                    CASE WHEN total.total > 0 THEN ROUND(agg.amount_cents::numeric / total.total * 100, 1) ELSE 0 END AS percent,
                    c.color AS color,
                    'c:' || COALESCE(agg.category_id::text, 'null') AS bucket_key,
                    c.parent_id AS parent_category_id,
                    0 AS children_count
                FROM agg
                CROSS JOIN total
                LEFT JOIN categories c ON c.id = agg.category_id
                ORDER BY agg.amount_cents DESC
                """
                ),
                *params,
            )
        return [dict(r) for r in rows]

    async def get_by_tag(
        self, month: Optional[str] = None, tag_id: Optional[int] = None, viewer_user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        pool = await self._pool()
        conditions = [_expense_predicate("t")]
        params: List[Any] = []
        idx = 1
        if month:
            conditions.append(
                f"COALESCE(t.authorized_date, t.date) >= (${idx} || '-01')::date"
            )
            params.append(month)
            idx += 1
            conditions.append(
                f"COALESCE(t.authorized_date, t.date) < ((${idx} || '-01')::date + INTERVAL '1 month')"
            )
            params.append(month)
            idx += 1
        if tag_id:
            conditions.append(f"tt.tag_id = ${idx}")
            params.append(tag_id)
            idx += 1
        if not reports_include_plaid_sandbox():
            conditions.append("(t.source IS NULL OR t.source <> 'plaid_sandbox')")
        if viewer_user_id is not None:
            conditions.append(
                f"(NOT t.is_private OR EXISTS ("
                f"SELECT 1 FROM accounts _pa WHERE _pa.id = t.account_id AND _pa.user_id = ${idx}))"
            )
            params.append(viewer_user_id)
            idx += 1
        where = " AND ".join(conditions)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    tg.id AS tag_id,
                    tg.name AS tag_name,
                    tg.color AS tag_color,
                    SUM(t.amount_cents) AS amount_cents
                FROM transactions t
                JOIN transaction_tags tt ON tt.transaction_id = t.id
                JOIN tags tg ON tg.id = tt.tag_id
                WHERE {where}
                GROUP BY tg.id, tg.name, tg.color
                ORDER BY amount_cents DESC
                """,
                *params,
            )
        return [dict(r) for r in rows]

    async def get_top_merchants(
        self, month: Optional[str] = None, limit: int = 10, viewer_user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        pool = await self._pool()
        conditions = [
            _expense_predicate("t"),
            "t.merchant_name IS NOT NULL",
        ]
        params: List[Any] = []
        idx = 1
        if month:
            conditions.append(
                f"COALESCE(t.authorized_date, t.date) >= (${idx} || '-01')::date"
            )
            params.append(month)
            idx += 1
            conditions.append(
                f"COALESCE(t.authorized_date, t.date) < ((${idx} || '-01')::date + INTERVAL '1 month')"
            )
            params.append(month)
            idx += 1
        if not reports_include_plaid_sandbox():
            conditions.append("(t.source IS NULL OR t.source <> 'plaid_sandbox')")
        if viewer_user_id is not None:
            conditions.append(
                f"(NOT t.is_private OR EXISTS ("
                f"SELECT 1 FROM accounts _pa WHERE _pa.id = t.account_id AND _pa.user_id = ${idx}))"
            )
            params.append(viewer_user_id)
            idx += 1
        params.append(limit)
        where = " AND ".join(conditions)
        # Group by the *aliased* name so two Plaid merchants the user renamed
        # to the same string (e.g. "Whole Foods" and "WHOLEFDS #123" → both
        # "Groceries") aggregate into one row. Falls back to t.merchant_name
        # for any merchant without an alias. The COALESCE expression is
        # repeated in SELECT and GROUP BY because PostgreSQL does not
        # accept GROUP BY on a column alias.
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    COALESCE(ma.display_name, t.merchant_name) AS merchant_name,
                    BOOL_OR(ma.display_name IS NOT NULL)        AS is_aliased,
                    MAX(t.logo_url) AS logo_url,
                    SUM(t.amount_cents) AS amount_cents,
                    COUNT(*) AS transaction_count
                FROM transactions t
                {alias_join_sql("t", "ma")}
                WHERE {where}
                GROUP BY COALESCE(ma.display_name, t.merchant_name)
                ORDER BY amount_cents DESC
                LIMIT ${idx}
                """,
                *params,
            )
        return [dict(r) for r in rows]

    async def get_income_breakdown(
        self, month: str, viewer_user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Per-person income for a calendar month, broken down by the category the
        transaction was mapped to.

        A transaction is counted as income only when
        ``transaction_class = 'income'`` — the four-class classifier is the
        single source of truth. Ownership is resolved via the account
        (``accounts.user_id``); unassigned accounts show up as a ``null``
        user so the frontend can still surface them.

        Private transactions owned by other family members are filtered out
        for the requesting viewer, mirroring the rest of the reports module.

        Returns a dict shaped for the UI (see ``IncomeBreakdown``).
        """
        pool = await self._pool()
        private_filter = (
            _private_tx_filter_with_idx("t", 2) if viewer_user_id is not None else ""
        )
        params: list = [month]
        if viewer_user_id is not None:
            params.append(viewer_user_id)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    a.user_id                     AS user_id,
                    u.username                    AS username,
                    t.category_id                 AS category_id,
                    COALESCE(c.name, 'Uncategorized') AS category_name,
                    c.color                       AS category_color,
                    SUM(-t.amount_cents)          AS amount_cents,
                    COUNT(*)                      AS transaction_count
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                LEFT JOIN users u ON u.id = a.user_id
                LEFT JOIN categories c ON c.id = t.category_id
                WHERE COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                  AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                  AND {_income_predicate("t")}
                  {_sandbox_tx_filter("t")}
                  {private_filter}
                GROUP BY a.user_id, u.username, t.category_id, c.name, c.color
                ORDER BY a.user_id NULLS LAST, amount_cents DESC
                """,
                *params,
            )

        users_by_id: Dict[Any, Dict[str, Any]] = {}
        total = 0
        for r in rows:
            user_key = r["user_id"]
            bucket = users_by_id.get(user_key)
            if bucket is None:
                bucket = {
                    "user_id": user_key,
                    "username": r["username"] or "Unassigned",
                    "amount_cents": 0,
                    "sources": [],
                }
                users_by_id[user_key] = bucket
            amount = int(r["amount_cents"] or 0)
            bucket["amount_cents"] += amount
            total += amount
            bucket["sources"].append({
                "category_id": r["category_id"],
                "category_name": r["category_name"],
                "color": r["category_color"],
                "amount_cents": amount,
                "transaction_count": int(r["transaction_count"] or 0),
            })

        users = sorted(
            users_by_id.values(),
            key=lambda row: row["amount_cents"],
            reverse=True,
        )
        return {
            "month": month,
            "total_cents": total,
            "users": users,
        }

    async def get_expense_breakdown(
        self, month: str, viewer_user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Per-person expenses for a calendar month, broken down by the category
        the transaction was mapped to. Mirror of ``get_income_breakdown`` so
        the Expenses tab can render the same structure with the opposite
        semantics.

        Uses ``SUM(amount_cents)`` (not ``SUM(CASE WHEN amount>0)``) so
        refunds reduce the category they came from — the accountant-correct
        behavior. Categories whose net spend for the month is zero (a
        refund exactly cancelling a purchase) are omitted to keep the UI
        clean. Internal transfers are excluded by the class predicate.
        """
        pool = await self._pool()
        private_filter = (
            _private_tx_filter_with_idx("t", 2) if viewer_user_id is not None else ""
        )
        params: list = [month]
        if viewer_user_id is not None:
            params.append(viewer_user_id)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    a.user_id                     AS user_id,
                    u.username                    AS username,
                    t.category_id                 AS category_id,
                    COALESCE(c.name, 'Uncategorized') AS category_name,
                    c.color                       AS category_color,
                    SUM(t.amount_cents)           AS amount_cents,
                    COUNT(*)                      AS transaction_count
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                LEFT JOIN users u ON u.id = a.user_id
                LEFT JOIN categories c ON c.id = t.category_id
                WHERE COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                  AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                  AND {_expense_predicate("t")}
                  {_sandbox_tx_filter("t")}
                  {private_filter}
                GROUP BY a.user_id, u.username, t.category_id, c.name, c.color
                HAVING SUM(t.amount_cents) <> 0
                ORDER BY a.user_id NULLS LAST, amount_cents DESC
                """,
                *params,
            )

        users_by_id: Dict[Any, Dict[str, Any]] = {}
        total = 0
        for r in rows:
            user_key = r["user_id"]
            bucket = users_by_id.get(user_key)
            if bucket is None:
                bucket = {
                    "user_id": user_key,
                    "username": r["username"] or "Unassigned",
                    "amount_cents": 0,
                    "sources": [],
                }
                users_by_id[user_key] = bucket
            amount = int(r["amount_cents"] or 0)
            bucket["amount_cents"] += amount
            total += amount
            bucket["sources"].append({
                "category_id": r["category_id"],
                "category_name": r["category_name"],
                "color": r["category_color"],
                "amount_cents": amount,
                "transaction_count": int(r["transaction_count"] or 0),
            })

        users = sorted(
            users_by_id.values(),
            key=lambda row: row["amount_cents"],
            reverse=True,
        )
        return {
            "month": month,
            "total_cents": total,
            "users": users,
        }

    async def get_net_worth(self) -> Dict[str, Any]:
        """Return today's net-worth composition + comparison deltas + per-account breakdown.

        Backwards-compatible: the four flat ``*_cents`` fields are still in
        the response, in the same shape the previous /api/reports/net-worth
        clients consumed. Everything else is additive context for the
        redesigned Net Worth tab — clients that don't read the new fields
        keep working unchanged.

        Comparison windows pick the snapshot **closest to** the target
        anchor (30 days ago for MoM, 180 days for the 6-mo lookback). We
        accept anything within ±15 days of the MoM anchor and ±45 days of
        the 6-mo anchor; outside those windows we return ``None`` instead
        of comparing against an arbitrarily distant snapshot, which would
        be misleading.

        Per-account breakdown joins the accounts list with branding so
        the UI can render institution logos without a second roundtrip.
        Investment holdings are summed *into* the parent account row so
        the breakdown stays one row per account.
        """
        from datetime import timedelta

        pool = await self._pool()
        async with pool.acquire() as conn:
            liquid = await conn.fetchval(
                "SELECT COALESCE(SUM(current_balance_cents), 0) FROM accounts WHERE type = 'depository' AND is_active"
            )
            investments = await conn.fetchval(
                "SELECT COALESCE(SUM(institution_value_cents), 0) FROM investment_holdings h JOIN accounts a ON a.id = h.account_id WHERE a.is_active"
            )
            debt = await conn.fetchval(
                "SELECT COALESCE(SUM(current_balance_cents), 0) FROM accounts WHERE type IN ('credit','loan') AND is_active"
            )
            # Postgres SUM(BIGINT) returns NUMERIC, which asyncpg surfaces as
            # Decimal. Downstream we feed these into the debt-payoff math
            # ``(delta / span_days) * 30`` and ``debt / per_month``; mixing
            # Decimal with a float literal raises ``TypeError`` (Python forbids
            # implicit Decimal*float). Cast to int up front — these are cents,
            # always whole numbers — so every derived value stays in plain
            # ``int`` / ``float`` arithmetic.
            liquid = int(liquid or 0)
            investments = int(investments or 0)
            debt = int(debt or 0)
            net = liquid + investments - debt

            # Per-account breakdown. Investment holdings are pre-aggregated
            # into ``inv_value`` and folded into the depository row sum so
            # the breakdown shows one tile per account, not one per holding.
            account_rows = await conn.fetch(
                """
                SELECT
                    a.id, a.name, a.official_name, a.mask, a.type, a.subtype,
                    a.current_balance_cents,
                    a.user_id, a.plaid_account_id,
                    pi.institution_name, pi.institution_logo, pi.institution_color,
                    u.username AS owner_username,
                    COALESCE((
                        SELECT SUM(h.institution_value_cents)
                        FROM investment_holdings h
                        WHERE h.account_id = a.id
                    ), 0) AS holdings_value_cents
                FROM accounts a
                LEFT JOIN plaid_items pi ON a.plaid_item_id = pi.item_id
                LEFT JOIN users u ON a.user_id = u.id
                WHERE a.is_active = TRUE
                  AND a.type IN ('depository','credit','loan','investment')
                ORDER BY a.type, a.name
                """,
            )

            # Comparison snapshots. Anchor at today, look up the snapshot
            # closest to (today - delta) within tolerance.
            today = date.today()

            async def _closest_snapshot(target: date, tolerance_days: int):
                lo = target - timedelta(days=tolerance_days)
                hi = target + timedelta(days=tolerance_days)
                return await conn.fetchrow(
                    """
                    SELECT snapshot_date, net_worth_cents
                    FROM net_worth_snapshots
                    WHERE snapshot_date BETWEEN $1 AND $2
                    ORDER BY ABS(snapshot_date - $3) ASC, snapshot_date DESC
                    LIMIT 1
                    """,
                    lo, hi, target,
                )

            mom_snap = await _closest_snapshot(today - timedelta(days=30), 15)
            six_mo_snap = await _closest_snapshot(today - timedelta(days=180), 45)

            # Trajectory for debt-payoff projection: pick the **6-month**
            # comparison if available (more stable than MoM), else fall
            # back to MoM. Only meaningful when (a) net is rising and (b)
            # there's outstanding debt.
            payoff_months: Optional[int] = None
            if debt > 0:
                trajectory_snap = six_mo_snap or mom_snap
                if trajectory_snap is not None:
                    span_days = (today - trajectory_snap["snapshot_date"]).days
                    delta_total = net - int(trajectory_snap["net_worth_cents"])
                    if span_days > 0 and delta_total > 0:
                        # Cents per day → cents per month (assume 30 days).
                        # ``delta_total / span_days`` is float in Py3; the
                        # ``30`` multiplier is an int on purpose — see the
                        # int() casts above for the original Decimal/float
                        # mixing trap.
                        per_month = (delta_total / span_days) * 30
                        if per_month > 0:
                            months = int(round(debt / per_month))
                            # Cap at 600mo (50yr) — anything longer is noise
                            if 0 < months <= 600:
                                payoff_months = months

        accounts: List[Dict[str, Any]] = []
        for r in account_rows:
            atype = r["type"]
            is_debt = atype in ("credit", "loan")
            # Pick the meaningful balance for the account's role:
            # - debt accounts → current balance (already non-negative)
            # - investment accounts → sum of holdings if available, else
            #   the account's stored balance
            # - depository → current balance
            if atype == "investment":
                bal = int(r["holdings_value_cents"] or 0) or int(r["current_balance_cents"] or 0)
            else:
                bal = int(r["current_balance_cents"] or 0)
            # Skip zero-balance accounts to keep the breakdown honest —
            # an empty Cash wallet shouldn't take a tile slot.
            if bal == 0:
                continue
            accounts.append({
                "id": r["id"],
                "name": r["name"],
                "official_name": r["official_name"],
                "mask": r["mask"],
                "type": atype,
                "subtype": r["subtype"],
                "role": "debt" if is_debt else "asset",
                "balance_cents": abs(bal),
                "owner_username": r["owner_username"],
                "institution_name": r["institution_name"],
                "institution_logo": r["institution_logo"],
                "institution_color": r["institution_color"],
                "is_cash_wallet": (
                    r["plaid_account_id"] is None
                    and atype == "depository"
                    and (r["subtype"] or "") == "cash"
                ),
            })

        # Final ordering: assets first (largest first), then debts (largest
        # first). The UI uses two side-by-side columns so this gives both
        # sides their natural sort.
        accounts.sort(key=lambda a: (0 if a["role"] == "asset" else 1, -a["balance_cents"]))

        return {
            "liquid_cents": liquid,
            "investment_cents": investments,
            "debt_cents": debt,
            "net_worth_cents": net,
            "mom_delta_cents": (
                net - int(mom_snap["net_worth_cents"]) if mom_snap is not None else None
            ),
            "six_month_delta_cents": (
                net - int(six_mo_snap["net_worth_cents"]) if six_mo_snap is not None else None
            ),
            "mom_compared_to": mom_snap["snapshot_date"] if mom_snap is not None else None,
            "six_month_compared_to": six_mo_snap["snapshot_date"] if six_mo_snap is not None else None,
            "accounts": accounts,
            "debt_payoff_months": payoff_months,
        }

    async def get_net_worth_history(self, months: int = 12) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT snapshot_date, liquid_cents, investment_cents, debt_cents, net_worth_cents
                FROM net_worth_snapshots
                ORDER BY snapshot_date DESC
                LIMIT $1
                """,
                months,
            )
        return [dict(r) for r in reversed(rows)]

    async def snapshot_net_worth(self) -> Dict[str, Any]:
        """Capture current net worth into net_worth_snapshots (called after each sync)."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            liquid = await conn.fetchval(
                "SELECT COALESCE(SUM(current_balance_cents), 0) FROM accounts WHERE type = 'depository' AND is_active"
            )
            investments = await conn.fetchval(
                "SELECT COALESCE(SUM(institution_value_cents), 0) FROM investment_holdings h JOIN accounts a ON a.id = h.account_id WHERE a.is_active"
            )
            debt = await conn.fetchval(
                "SELECT COALESCE(SUM(current_balance_cents), 0) FROM accounts WHERE type IN ('credit','loan') AND is_active"
            )
            # Same int() cast as get_net_worth — keeps the snapshot row
            # writing ints into the BIGINT columns and matches the read path.
            liquid = int(liquid or 0)
            investments = int(investments or 0)
            debt = int(debt or 0)
            net = liquid + investments - debt
            today = date.today()
            row = await conn.fetchrow(
                """
                INSERT INTO net_worth_snapshots (snapshot_date, liquid_cents, investment_cents, debt_cents, net_worth_cents)
                VALUES ($1,$2,$3,$4,$5)
                ON CONFLICT (snapshot_date) DO UPDATE SET
                    liquid_cents     = EXCLUDED.liquid_cents,
                    investment_cents = EXCLUDED.investment_cents,
                    debt_cents       = EXCLUDED.debt_cents,
                    net_worth_cents  = EXCLUDED.net_worth_cents
                RETURNING *
                """,
                today, liquid, investments, debt, net,
            )
        return dict(row)

    async def get_financial_health_data(
        self, viewer_user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Gather raw data needed for financial health score calculation.

        Window contract (see ``docs/reports-math.md``):

        - ``monthly_income_cents``, ``monthly_expenses_cents`` are both
          **3-month averages over completed months** so the savings-rate
          metric in ``compute_health_score`` compares apples to apples.
          Using partial month-to-date for expenses (as V2.1 did) made
          early-month scores look artificially great.
        - ``annual_income_cents`` is the **real 12-month income sum** (not
          ``monthly_income * 12``) so DTI is not distorted by short-term
          paycheck spikes.
        - ``total_debt_cents`` reflects **credit balances only** — loans
          and mortgages are tracked separately via ``mortgage_loan_cents``
          so DTI does not punish users with a mortgage. The advice string
          still surfaces the loan balance so it is not hidden.

        When ``viewer_user_id`` is provided, private transactions owned by
        other users are excluded from the income/expense aggregates so
        they do not leak into the viewer's health score.
        """
        pool = await self._pool()
        async with pool.acquire() as conn:
            # Monthly income: average over the last 3 completed months.
            income_filter = (
                _private_tx_filter_with_idx("", 1) if viewer_user_id is not None else ""
            )
            income_params: list = []
            if viewer_user_id is not None:
                income_params.append(viewer_user_id)
            monthly_income = await conn.fetchval(
                f"""
                SELECT COALESCE(AVG(monthly_total), 0)
                FROM (
                    SELECT
                        TO_CHAR(COALESCE(authorized_date, date), 'YYYY-MM') AS m,
                        SUM(-amount_cents) AS monthly_total
                    FROM transactions
                    WHERE {_income_predicate("")}
                      AND COALESCE(authorized_date, date) >= (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '3 months')
                      AND COALESCE(authorized_date, date) < DATE_TRUNC('month', CURRENT_DATE)
                      {_sandbox_tx_filter_no_alias()}
                      {income_filter}
                    GROUP BY m
                ) sub
                """,
                *income_params,
            )
            monthly_income = int(monthly_income or 0)
            # Real annual income: sum over last 12 completed months.
            annual_filter = (
                _private_tx_filter_with_idx("", 1) if viewer_user_id is not None else ""
            )
            annual_params: list = []
            if viewer_user_id is not None:
                annual_params.append(viewer_user_id)
            annual_income = await conn.fetchval(
                f"""
                SELECT COALESCE(SUM(-amount_cents), 0)
                FROM transactions
                WHERE {_income_predicate("")}
                  AND COALESCE(authorized_date, date) >= (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '12 months')
                  AND COALESCE(authorized_date, date) < DATE_TRUNC('month', CURRENT_DATE)
                  {_sandbox_tx_filter_no_alias()}
                  {annual_filter}
                """,
                *annual_params,
            )
            annual_income = int(annual_income or 0)
            # Monthly expenses: 3-month average of completed months, symmetric
            # with monthly_income so savings_rate is well-defined.
            exp_filter = (
                _private_tx_filter_with_idx("", 1) if viewer_user_id is not None else ""
            )
            exp_params: list = []
            if viewer_user_id is not None:
                exp_params.append(viewer_user_id)
            monthly_expenses = await conn.fetchval(
                f"""
                SELECT COALESCE(AVG(monthly_total), 0)
                FROM (
                    SELECT
                        TO_CHAR(COALESCE(authorized_date, date), 'YYYY-MM') AS m,
                        SUM(amount_cents) AS monthly_total
                    FROM transactions
                    WHERE {_expense_predicate("")}
                      AND COALESCE(authorized_date, date) >= (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '3 months')
                      AND COALESCE(authorized_date, date) < DATE_TRUNC('month', CURRENT_DATE)
                      {_sandbox_tx_filter_no_alias()}
                      {exp_filter}
                    GROUP BY m
                ) sub
                """,
                *exp_params,
            )
            # Average monthly expenses (last 6 months) — used by the emergency
            # fund calculation; kept separate from the savings-rate input.
            avg_filter = (
                _private_tx_filter_with_idx("", 1) if viewer_user_id is not None else ""
            )
            avg_params: list = []
            if viewer_user_id is not None:
                avg_params.append(viewer_user_id)
            avg_expenses = await conn.fetchval(
                f"""
                SELECT COALESCE(AVG(monthly_total), 0)
                FROM (
                    SELECT
                        TO_CHAR(COALESCE(authorized_date, date), 'YYYY-MM') AS m,
                        SUM(amount_cents) AS monthly_total
                    FROM transactions
                    WHERE {_expense_predicate("")}
                      AND COALESCE(authorized_date, date) >= (CURRENT_DATE - INTERVAL '6 months')
                      {_sandbox_tx_filter_no_alias()}
                      {avg_filter}
                    GROUP BY m
                ) sub
                """,
                *avg_params,
            )
            # DTI uses credit-card debt only; mortgages/loans are surfaced
            # separately so the score is not distorted by normal home debt.
            credit_debt = await conn.fetchval(
                "SELECT COALESCE(SUM(current_balance_cents), 0) FROM accounts WHERE type = 'credit' AND is_active"
            )
            mortgage_loan = await conn.fetchval(
                "SELECT COALESCE(SUM(current_balance_cents), 0) FROM accounts WHERE type = 'loan' AND is_active"
            )
            credit_limit = await conn.fetchval(
                "SELECT COALESCE(SUM(credit_limit_cents), 0) FROM accounts WHERE type = 'credit' AND is_active AND credit_limit_cents IS NOT NULL"
            )
            liquid = await conn.fetchval(
                "SELECT COALESCE(SUM(current_balance_cents), 0) FROM accounts WHERE type = 'depository' AND is_active"
            )
            has_overdue = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM accounts WHERE is_overdue = TRUE AND is_active)"
            )
        return {
            "total_debt_cents": int(credit_debt or 0),
            "mortgage_loan_cents": int(mortgage_loan or 0),
            "annual_income_cents": annual_income,
            "monthly_income_cents": monthly_income,
            "monthly_expenses_cents": int(monthly_expenses or 0),
            "total_credit_limit_cents": credit_limit or 0,
            "total_credit_balance_cents": int(credit_debt or 0),
            "liquid_balance_cents": liquid or 0,
            "avg_monthly_expenses_cents": int(avg_expenses or 0),
            "has_overdue": bool(has_overdue),
        }

    async def get_diagnostics(self, month: str) -> Dict[str, Any]:
        """
        Owner-only diagnostic snapshot for ``month`` — surfaces rows that the
        classifier found suspicious or could not confidently bucket. Used by
        the owner (and automated tests) to spot data-quality issues without
        running ad-hoc SQL.

        Returned sections mirror ``docs/reports-math.md § 3`` so each
        surfaced row maps back to the rule that could not fire. The endpoint
        ignores the viewer filter — the owner is meant to see everything,
        including private transactions belonging to other family members.
        """
        pool = await self._pool()
        async with pool.acquire() as conn:
            suspicious_income = await conn.fetch(
                """
                SELECT t.id, t.date, t.amount_cents, t.merchant_name, t.name,
                       t.pfc_primary, t.pfc_detailed,
                       COALESCE(c.name, 'Uncategorized') AS category_name,
                       t.transaction_class
                FROM transactions t
                LEFT JOIN categories c ON c.id = t.category_id
                WHERE COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                  AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                  AND EXISTS (SELECT 1 FROM categories _c WHERE _c.id = t.category_id AND _c.is_income = TRUE)
                  AND t.amount_cents > 0
                ORDER BY t.amount_cents DESC
                LIMIT 50
                """,
                month,
            )
            unmatched_transfers = await conn.fetch(
                """
                SELECT t.id, t.date, t.amount_cents, t.merchant_name, t.name,
                       t.pfc_primary, t.transaction_class
                FROM transactions t
                WHERE COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                  AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                  AND t.pfc_primary IN ('TRANSFER_IN', 'TRANSFER_OUT', 'LOAN_PAYMENTS')
                  AND t.transaction_class <> 'internal_transfer'
                ORDER BY ABS(t.amount_cents) DESC
                LIMIT 50
                """,
                month,
            )
            uncategorized = await conn.fetch(
                """
                SELECT t.id, t.date, t.amount_cents, t.merchant_name, t.name,
                       t.pfc_primary, a.type AS account_type,
                       COALESCE(c.name, 'Uncategorized') AS category_name
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                LEFT JOIN categories c ON c.id = t.category_id
                WHERE COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                  AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                  AND t.transaction_class = 'uncategorized'
                  AND ABS(t.amount_cents) > 1000
                ORDER BY ABS(t.amount_cents) DESC
                LIMIT 50
                """,
                month,
            )
            # Rule 5.5 (orphan TRANSFER_IN on a depository → income) is a
            # blunt instrument: it correctly tags wire deposits from
            # untracked banks as income, but it ALSO swallows ACH refunds
            # that Plaid happened to label TRANSFER_IN. The income bucket
            # then double-inflates: the original purchase keeps its
            # ``expense`` row from N days ago, and the matching refund
            # arrives as ``income`` instead of reducing the expense.
            #
            # We surface (not auto-fix) any rule-5.5 income row whose
            # merchant_entity_id matches a recent expense from the same
            # entity within the last 60 days. Owner can confirm and pin
            # the row to ``expense`` via the modal — manual_class_override
            # is sacred and the carryover fix landed alongside this
            # diagnostic so the pin survives the next sync.
            possible_refunds = await conn.fetch(
                """
                SELECT t.id, t.date, t.amount_cents, t.merchant_name, t.name,
                       t.pfc_primary, t.merchant_entity_id,
                       COALESCE(c.name, 'Uncategorized') AS category_name,
                       (
                         SELECT MAX(e.date)
                         FROM transactions e
                         WHERE e.merchant_entity_id = t.merchant_entity_id
                           AND e.transaction_class = 'expense'
                           AND e.id <> t.id
                           AND e.date BETWEEN t.date - INTERVAL '60 days' AND t.date
                       ) AS recent_expense_date
                FROM transactions t
                LEFT JOIN categories c ON c.id = t.category_id
                WHERE COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                  AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                  AND t.transaction_class = 'income'
                  AND t.pfc_primary = 'TRANSFER_IN'
                  AND t.manual_class_override IS NULL
                  AND t.merchant_entity_id IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM transactions e
                    WHERE e.merchant_entity_id = t.merchant_entity_id
                      AND e.transaction_class = 'expense'
                      AND e.id <> t.id
                      AND e.date BETWEEN t.date - INTERVAL '60 days' AND t.date
                  )
                ORDER BY ABS(t.amount_cents) DESC
                LIMIT 50
                """,
                month,
            )
            counts = await conn.fetchrow(
                """
                SELECT
                    SUM(CASE WHEN transaction_class = 'income' THEN 1 ELSE 0 END) AS income,
                    SUM(CASE WHEN transaction_class = 'expense' THEN 1 ELSE 0 END) AS expense,
                    SUM(CASE WHEN transaction_class = 'internal_transfer' THEN 1 ELSE 0 END) AS internal_transfer,
                    SUM(CASE WHEN transaction_class = 'uncategorized' THEN 1 ELSE 0 END) AS uncategorized,
                    COUNT(*) AS total
                FROM transactions
                WHERE COALESCE(authorized_date, date) >= ($1 || '-01')::date
                  AND COALESCE(authorized_date, date) < (($1 || '-01')::date + INTERVAL '1 month')
                """,
                month,
            )
        return {
            "month": month,
            "counts": {
                "income": int(counts["income"] or 0),
                "expense": int(counts["expense"] or 0),
                "internal_transfer": int(counts["internal_transfer"] or 0),
                "uncategorized": int(counts["uncategorized"] or 0),
                "total": int(counts["total"] or 0),
            },
            "suspicious_income_category_with_positive_amount": [
                dict(r) for r in suspicious_income
            ],
            "transfer_pfc_not_classified_as_internal": [
                dict(r) for r in unmatched_transfers
            ],
            "large_uncategorized": [dict(r) for r in uncategorized],
            "possible_refunds_misclassified_as_income": [
                dict(r) for r in possible_refunds
            ],
        }
