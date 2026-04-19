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
        Only counts expenses (amount_cents > 0). Excludes ``plaid_sandbox`` when
        ``reports_include_plaid_sandbox()`` is false. Excludes private transactions
        from other users when viewer_user_id is provided. Excludes rows flagged as
        internal transfers (``is_internal_transfer = TRUE``) so spouse-to-spouse
        Zelle doesn't inflate the "spent" total.
        """
        pool = await self._pool()
        sandbox_ex = "" if reports_include_plaid_sandbox() else "AND t.source != 'plaid_sandbox'"
        params: List[Any] = [month]
        private_ex = ""
        if viewer_user_id is not None:
            params.append(viewer_user_id)
            private_ex = (
                f"AND (NOT t.is_private OR EXISTS ("
                f"SELECT 1 FROM accounts _pa WHERE _pa.id = t.account_id AND _pa.user_id = $2))"
            )
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                WITH actual AS (
                    -- Transactions without splits: use their own category + parent link
                    SELECT
                        t.category_id,
                        c.parent_id,
                        SUM(t.amount_cents) AS spent
                    FROM transactions t
                    LEFT JOIN categories c ON c.id = t.category_id
                    WHERE
                        t.amount_cents > 0
                        AND NOT t.is_internal_transfer
                        {sandbox_ex}
                        {private_ex}
                        AND COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                        AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                        AND NOT EXISTS (
                            SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id
                        )
                    GROUP BY t.category_id, c.parent_id

                    UNION ALL

                    -- Transactions with splits: use split category + its parent link
                    SELECT
                        ts.category_id,
                        sc.parent_id,
                        SUM(ts.amount_cents) AS spent
                    FROM transaction_splits ts
                    JOIN transactions t ON t.id = ts.parent_transaction_id
                    LEFT JOIN categories sc ON sc.id = ts.category_id
                    WHERE
                        t.amount_cents > 0
                        AND NOT t.is_internal_transfer
                        {sandbox_ex}
                        {private_ex}
                        AND COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                        AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                    GROUP BY ts.category_id, sc.parent_id
                ),
                -- Child-level aggregate: spent on a specific detailed category.
                aggregated_child AS (
                    SELECT category_id, SUM(spent) AS actual_cents
                    FROM actual
                    WHERE category_id IS NOT NULL
                    GROUP BY category_id
                ),
                -- Parent-level aggregate: for each bucket (self or parent), sum spending.
                aggregated_parent AS (
                    SELECT COALESCE(parent_id, category_id) AS bucket_id, SUM(spent) AS actual_cents
                    FROM actual
                    WHERE category_id IS NOT NULL
                    GROUP BY COALESCE(parent_id, category_id)
                )
                SELECT
                    cb.id,
                    cb.category_id,
                    c.name AS category_name,
                    COALESCE(c.color, '#3b82f6') AS category_color,
                    cb.month,
                    cb.budget_cents,
                    COALESCE(
                        CASE
                            WHEN c.parent_id IS NULL THEN ap.actual_cents
                            ELSE ach.actual_cents
                        END,
                        0
                    ) AS actual_cents,
                    cb.budget_cents - COALESCE(
                        CASE
                            WHEN c.parent_id IS NULL THEN ap.actual_cents
                            ELSE ach.actual_cents
                        END,
                        0
                    ) AS remaining_cents,
                    CASE
                        WHEN cb.budget_cents = 0 THEN 0
                        ELSE ROUND(
                            COALESCE(
                                CASE
                                    WHEN c.parent_id IS NULL THEN ap.actual_cents
                                    ELSE ach.actual_cents
                                END,
                                0
                            )::numeric / cb.budget_cents * 100,
                            1
                        )
                    END AS percent_used
                FROM category_budgets cb
                JOIN categories c ON c.id = cb.category_id
                LEFT JOIN aggregated_child  ach ON ach.category_id = cb.category_id
                LEFT JOIN aggregated_parent ap  ON ap.bucket_id   = cb.category_id
                WHERE cb.month = $1
                ORDER BY percent_used DESC
                """,
                *params,
            )
        return [dict(r) for r in rows]
