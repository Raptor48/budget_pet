"""
BudgetsRepository — category_budgets CRUD + progress calculation.

Progress calculation respects split transactions:
- If a transaction has splits, the category-specific split amounts are used.
- If no splits, the transaction's own category_id + amount_cents are used.
"""
import logging
from typing import Any, Dict, List, Optional

from web.db import get_pool
from web.env_flags import reports_include_plaid_sandbox

logger = logging.getLogger(__name__)


class BudgetsRepository:
    async def _pool(self):
        return await get_pool()

    async def list_budgets(self, month: Optional[str] = None) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            if month:
                rows = await conn.fetch(
                    "SELECT * FROM category_budgets WHERE month = $1 ORDER BY id", month
                )
            else:
                rows = await conn.fetch("SELECT * FROM category_budgets ORDER BY month DESC, id")
        return [dict(r) for r in rows]

    async def get_budget(self, budget_id: int) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM category_budgets WHERE id = $1", budget_id)
        return dict(row) if row else None

    async def create_budget(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Upsert a budget row for (category, month).

        Validates against hierarchy conflicts:
        - If `category_id` is a detailed child and a parent-level budget already
          exists for that month, the detailed budget is rejected (parent would
          over-count).
        - If `category_id` is a primary parent and any of its children already
          has a budget for that month, the primary budget is rejected.
        Callers should surface the ValueError as a 409.
        """
        pool = await self._pool()
        category_id = int(data["category_id"])
        month = data["month"]
        async with pool.acquire() as conn:
            category = await conn.fetchrow(
                "SELECT id, parent_id FROM categories WHERE id = $1", category_id
            )
            if not category:
                raise ValueError("Category not found")
            parent_id = category["parent_id"]
            if parent_id is not None:
                # Child row: reject if a budget already exists on the parent for
                # the same month. Allow upsert of the same row (same category_id).
                parent_budget = await conn.fetchrow(
                    """
                    SELECT 1 FROM category_budgets
                    WHERE category_id = $1 AND month = $2
                    """,
                    parent_id,
                    month,
                )
                if parent_budget:
                    raise ValueError(
                        "A parent-category budget already exists for this month; "
                        "remove it before creating a more precise child budget."
                    )
            else:
                # Parent row (or top-level custom): reject if any child already
                # has a budget this month.
                child_budget = await conn.fetchrow(
                    """
                    SELECT 1 FROM category_budgets cb
                    JOIN categories c ON c.id = cb.category_id
                    WHERE c.parent_id = $1 AND cb.month = $2
                    """,
                    category_id,
                    month,
                )
                if child_budget:
                    raise ValueError(
                        "A more precise child budget already exists for this month; "
                        "remove child budgets before setting a parent-level budget."
                    )

            row = await conn.fetchrow(
                """
                INSERT INTO category_budgets (category_id, month, budget_cents)
                VALUES ($1,$2,$3)
                ON CONFLICT (category_id, month) DO UPDATE SET budget_cents = EXCLUDED.budget_cents
                RETURNING *
                """,
                category_id,
                month,
                data["budget_cents"],
            )
        return dict(row)

    async def update_budget(
        self, budget_id: int, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if "budget_cents" not in data:
            return await self.get_budget(budget_id)
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE category_budgets SET budget_cents = $2 WHERE id = $1 RETURNING *",
                budget_id,
                data["budget_cents"],
            )
        return dict(row) if row else None

    async def delete_budget(self, budget_id: int) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM category_budgets WHERE id = $1", budget_id
            )
        return result != "DELETE 0"

    async def copy_budgets(self, from_month: str, to_month: str) -> Dict[str, int]:
        """Copy every (category_id, budget_cents) row from ``from_month`` to ``to_month``.

        Idempotent: rows that already exist in ``to_month`` for the same
        ``category_id`` are left untouched and counted as ``skipped_existing``
        (so the user can run this twice without nuking edits they've already
        made on the new month). Hierarchy guard isn't re-checked — categories
        that conflicted in ``from_month`` could not have been written there in
        the first place, so the copy can only produce a valid configuration.
        """
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    INSERT INTO category_budgets (category_id, month, budget_cents)
                    SELECT category_id, $2, budget_cents
                    FROM category_budgets
                    WHERE month = $1
                    ON CONFLICT (category_id, month) DO NOTHING
                    RETURNING id
                    """,
                    from_month,
                    to_month,
                )
                source_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM category_budgets WHERE month = $1",
                    from_month,
                )
        copied = len(rows)
        return {
            "from_month": from_month,
            "to_month": to_month,
            "copied": copied,
            "skipped_existing": int(source_count or 0) - copied,
        }

    async def get_history(
        self,
        months: int,
        viewer_user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return one row per category that has had a budget in the last
        ``months`` calendar months, with budget + actual for each month.

        Cells where the user did not set a budget come back with
        ``budget_cents = 0`` and ``ratio = None`` so the heatmap can render
        a neutral "no budget" cell (vs. a green "under budget" one).
        Categories that never had a budget in the window are excluded.
        """
        pool = await self._pool()
        sandbox_ex = "" if reports_include_plaid_sandbox() else "AND t.source != 'plaid_sandbox'"
        params: List[Any] = [months]
        private_ex = ""
        if viewer_user_id is not None:
            params.append(viewer_user_id)
            private_ex = (
                "AND (NOT t.is_private OR EXISTS ("
                "SELECT 1 FROM accounts _pa WHERE _pa.id = t.account_id AND _pa.user_id = $2))"
            )
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                WITH window_months AS (
                    SELECT to_char(
                        date_trunc('month', CURRENT_DATE) - (n || ' months')::interval,
                        'YYYY-MM'
                    ) AS month
                    FROM generate_series(0, $1::int - 1) AS n
                ),
                budgets_in_window AS (
                    SELECT cb.category_id, cb.month, cb.budget_cents
                    FROM category_budgets cb
                    WHERE cb.month IN (SELECT month FROM window_months)
                ),
                tracked_categories AS (
                    SELECT DISTINCT category_id FROM budgets_in_window
                ),
                actual AS (
                    SELECT t.category_id,
                           c.parent_id,
                           to_char(COALESCE(t.authorized_date, t.date), 'YYYY-MM') AS month,
                           SUM(t.amount_cents) AS spent
                    FROM transactions t
                    LEFT JOIN categories c ON c.id = t.category_id
                    WHERE t.transaction_class = 'expense'
                          {sandbox_ex}
                          {private_ex}
                          AND COALESCE(t.authorized_date, t.date) >=
                              date_trunc('month',
                                  CURRENT_DATE - (($1::int - 1) || ' months')::interval)
                          AND NOT EXISTS (
                              SELECT 1 FROM transaction_splits ts
                              WHERE ts.parent_transaction_id = t.id
                          )
                    GROUP BY t.category_id, c.parent_id, month

                    UNION ALL

                    SELECT ts.category_id,
                           sc.parent_id,
                           to_char(COALESCE(t.authorized_date, t.date), 'YYYY-MM') AS month,
                           SUM(ts.amount_cents) AS spent
                    FROM transaction_splits ts
                    JOIN transactions t ON t.id = ts.parent_transaction_id
                    LEFT JOIN categories sc ON sc.id = ts.category_id
                    WHERE t.transaction_class = 'expense'
                          {sandbox_ex}
                          {private_ex}
                          AND COALESCE(t.authorized_date, t.date) >=
                              date_trunc('month',
                                  CURRENT_DATE - (($1::int - 1) || ' months')::interval)
                    GROUP BY ts.category_id, sc.parent_id, month
                ),
                aggregated_child AS (
                    SELECT category_id, month, SUM(spent) AS actual_cents
                    FROM actual
                    WHERE category_id IS NOT NULL
                    GROUP BY category_id, month
                ),
                aggregated_parent AS (
                    SELECT COALESCE(parent_id, category_id) AS bucket_id,
                           month,
                           SUM(spent) AS actual_cents
                    FROM actual
                    WHERE category_id IS NOT NULL
                    GROUP BY COALESCE(parent_id, category_id), month
                )
                SELECT
                    c.id   AS category_id,
                    c.name AS category_name,
                    COALESCE(c.color, '#3b82f6') AS category_color,
                    c.parent_id,
                    wm.month,
                    COALESCE(biw.budget_cents, 0) AS budget_cents,
                    COALESCE(
                        CASE
                            WHEN c.parent_id IS NULL THEN ap.actual_cents
                            ELSE ach.actual_cents
                        END,
                        0
                    ) AS actual_cents
                FROM tracked_categories tc
                JOIN categories c ON c.id = tc.category_id
                CROSS JOIN window_months wm
                LEFT JOIN budgets_in_window  biw
                    ON biw.category_id = c.id AND biw.month = wm.month
                LEFT JOIN aggregated_child   ach
                    ON ach.category_id = c.id AND ach.month = wm.month
                LEFT JOIN aggregated_parent  ap
                    ON ap.bucket_id   = c.id AND ap.month = wm.month
                ORDER BY c.name, wm.month
                """,
                *params,
            )
        # Group rows by category and assemble the per-category timeline.
        by_cat: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            cid = r["category_id"]
            entry = by_cat.setdefault(
                cid,
                {
                    "category_id": cid,
                    "category_name": r["category_name"],
                    "category_color": r["category_color"],
                    "parent_id": r["parent_id"],
                    "months": [],
                    "months_with_budget": 0,
                    "months_under_or_at": 0,
                },
            )
            budget = int(r["budget_cents"] or 0)
            actual = int(r["actual_cents"] or 0)
            ratio: Optional[float]
            if budget > 0:
                ratio = round(actual / budget, 4)
                entry["months_with_budget"] += 1
                if actual <= budget:
                    entry["months_under_or_at"] += 1
            else:
                ratio = None
            entry["months"].append(
                {
                    "month": r["month"],
                    "budget_cents": budget,
                    "actual_cents": actual,
                    "ratio": ratio,
                }
            )
        # Sort each category's months chronologically (oldest → newest) so
        # the heatmap reads left-to-right like a calendar.
        for entry in by_cat.values():
            entry["months"].sort(key=lambda m: m["month"])
        return list(by_cat.values())

    async def get_progress(self, month: str, viewer_user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        For each budget in the given month, return actual spending.

        Respects category hierarchy:
        - If the budget is on a *parent* (`parent_id IS NULL`), actuals sum
          transactions whose category is the parent itself OR any child (via
          `COALESCE(parent_id, id) = parent_id`).
        - If the budget is on a *child* (`parent_id IS NOT NULL`), actuals sum
          only transactions directly on that child.

        Actual spending uses splits if they exist, otherwise uses transaction.category_id.
        Only counts expenses (``transaction_class = 'expense'`` — see
        ``docs/reports-math.md``), which naturally excludes internal
        transfers and includes refunds as negative amounts that reduce the
        month's spend. Excludes ``plaid_sandbox`` when
        ``reports_include_plaid_sandbox()`` is false and private
        transactions from other users when ``viewer_user_id`` is provided.
        """
        pool = await self._pool()
        sandbox_ex = "" if reports_include_plaid_sandbox() else "AND t.source != 'plaid_sandbox'"
        # Previous month (YYYY-MM) for the dopamine "saved last month" badge.
        # Computed in Python so the SQL stays readable; both windows go in as
        # parameters and the query builds a per-month aggregation table.
        y, m = int(month[:4]), int(month[5:7])
        py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
        prev_month = f"{py:04d}-{pm:02d}"
        params: List[Any] = [month, prev_month]
        private_ex = ""
        if viewer_user_id is not None:
            params.append(viewer_user_id)
            private_ex = (
                "AND (NOT t.is_private OR EXISTS ("
                "SELECT 1 FROM accounts _pa WHERE _pa.id = t.account_id AND _pa.user_id = $3))"
            )
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                WITH window_months AS (
                    SELECT $1::text AS month UNION ALL SELECT $2::text
                ),
                actual AS (
                    -- Transactions without splits: use their own category + parent link
                    SELECT
                        t.category_id,
                        c.parent_id,
                        to_char(COALESCE(t.authorized_date, t.date), 'YYYY-MM') AS month,
                        SUM(t.amount_cents) AS spent
                    FROM transactions t
                    LEFT JOIN categories c ON c.id = t.category_id
                    WHERE
                        t.transaction_class = 'expense'
                        {sandbox_ex}
                        {private_ex}
                        AND to_char(COALESCE(t.authorized_date, t.date), 'YYYY-MM')
                            IN (SELECT month FROM window_months)
                        AND NOT EXISTS (
                            SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id
                        )
                    GROUP BY t.category_id, c.parent_id, month

                    UNION ALL

                    -- Transactions with splits: use split category + its parent link
                    SELECT
                        ts.category_id,
                        sc.parent_id,
                        to_char(COALESCE(t.authorized_date, t.date), 'YYYY-MM') AS month,
                        SUM(ts.amount_cents) AS spent
                    FROM transaction_splits ts
                    JOIN transactions t ON t.id = ts.parent_transaction_id
                    LEFT JOIN categories sc ON sc.id = ts.category_id
                    WHERE
                        t.transaction_class = 'expense'
                        {sandbox_ex}
                        {private_ex}
                        AND to_char(COALESCE(t.authorized_date, t.date), 'YYYY-MM')
                            IN (SELECT month FROM window_months)
                    GROUP BY ts.category_id, sc.parent_id, month
                ),
                -- Child-level aggregate: spent on a specific detailed category.
                aggregated_child AS (
                    SELECT category_id, month, SUM(spent) AS actual_cents
                    FROM actual
                    WHERE category_id IS NOT NULL
                    GROUP BY category_id, month
                ),
                -- Parent-level aggregate: for each bucket (self or parent), sum spending.
                aggregated_parent AS (
                    SELECT COALESCE(parent_id, category_id) AS bucket_id, month, SUM(spent) AS actual_cents
                    FROM actual
                    WHERE category_id IS NOT NULL
                    GROUP BY COALESCE(parent_id, category_id), month
                ),
                -- Per-category actuals for both target month and previous month.
                actuals_per_month AS (
                    SELECT
                        cb.category_id,
                        wm.month,
                        COALESCE(
                            CASE
                                WHEN c.parent_id IS NULL THEN ap.actual_cents
                                ELSE ach.actual_cents
                            END,
                            0
                        ) AS actual_cents
                    FROM category_budgets cb
                    JOIN categories c ON c.id = cb.category_id
                    CROSS JOIN window_months wm
                    LEFT JOIN aggregated_child  ach
                        ON ach.category_id = cb.category_id AND ach.month = wm.month
                    LEFT JOIN aggregated_parent ap
                        ON ap.bucket_id    = cb.category_id AND ap.month = wm.month
                    WHERE cb.month = $1
                ),
                -- Previous-month budget for the same category, if any.
                prev_budgets AS (
                    SELECT category_id, budget_cents
                    FROM category_budgets
                    WHERE month = $2
                )
                SELECT
                    cb.id,
                    cb.category_id,
                    c.name AS category_name,
                    COALESCE(c.color, '#3b82f6') AS category_color,
                    cb.month,
                    cb.budget_cents,
                    apm_now.actual_cents AS actual_cents,
                    cb.budget_cents - apm_now.actual_cents AS remaining_cents,
                    CASE
                        WHEN cb.budget_cents = 0 THEN 0
                        ELSE ROUND(apm_now.actual_cents::numeric / cb.budget_cents * 100, 1)
                    END AS percent_used,
                    CASE
                        WHEN pb.budget_cents IS NULL THEN NULL
                        ELSE pb.budget_cents - COALESCE(apm_prev.actual_cents, 0)
                    END AS previous_month_diff_cents
                FROM category_budgets cb
                JOIN categories c ON c.id = cb.category_id
                LEFT JOIN actuals_per_month apm_now
                    ON apm_now.category_id = cb.category_id AND apm_now.month = $1
                LEFT JOIN actuals_per_month apm_prev
                    ON apm_prev.category_id = cb.category_id AND apm_prev.month = $2
                LEFT JOIN prev_budgets pb ON pb.category_id = cb.category_id
                WHERE cb.month = $1
                ORDER BY percent_used DESC
                """,
                *params,
            )
        return [dict(r) for r in rows]
