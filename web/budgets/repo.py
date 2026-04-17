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
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO category_budgets (category_id, month, budget_cents)
                VALUES ($1,$2,$3)
                ON CONFLICT (category_id, month) DO UPDATE SET budget_cents = EXCLUDED.budget_cents
                RETURNING *
                """,
                data["category_id"],
                data["month"],
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

    async def get_progress(self, month: str) -> List[Dict[str, Any]]:
        """
        For each budget in the given month, return actual spending.
        Actual spending uses splits if they exist, otherwise uses transaction.category_id.
        Only counts expenses (amount_cents > 0). Excludes ``plaid_sandbox`` when
        ``reports_include_plaid_sandbox()`` is false (see ``web.env_flags``).
        """
        pool = await self._pool()
        sandbox_ex = "" if reports_include_plaid_sandbox() else "AND t.source != 'plaid_sandbox'"
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                WITH actual AS (
                    -- Transactions without splits: use their own category
                    SELECT
                        t.category_id,
                        SUM(t.amount_cents) AS spent
                    FROM transactions t
                    WHERE
                        t.amount_cents > 0
                        {sandbox_ex}
                        AND COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                        AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                        AND NOT EXISTS (
                            SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id
                        )
                    GROUP BY t.category_id

                    UNION ALL

                    -- Transactions with splits: use split category and amount
                    SELECT
                        ts.category_id,
                        SUM(ts.amount_cents) AS spent
                    FROM transaction_splits ts
                    JOIN transactions t ON t.id = ts.parent_transaction_id
                    WHERE
                        t.amount_cents > 0
                        {sandbox_ex}
                        AND COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                        AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                    GROUP BY ts.category_id
                ),
                aggregated AS (
                    SELECT category_id, SUM(spent) AS actual_cents
                    FROM actual
                    WHERE category_id IS NOT NULL
                    GROUP BY category_id
                )
                SELECT
                    cb.id,
                    cb.category_id,
                    c.name AS category_name,
                    COALESCE(c.color, '#3b82f6') AS category_color,
                    cb.month,
                    cb.budget_cents,
                    COALESCE(a.actual_cents, 0) AS actual_cents,
                    cb.budget_cents - COALESCE(a.actual_cents, 0) AS remaining_cents,
                    CASE
                        WHEN cb.budget_cents = 0 THEN 0
                        ELSE ROUND(COALESCE(a.actual_cents, 0)::numeric / cb.budget_cents * 100, 1)
                    END AS percent_used
                FROM category_budgets cb
                JOIN categories c ON c.id = cb.category_id
                LEFT JOIN aggregated a ON a.category_id = cb.category_id
                WHERE cb.month = $1
                ORDER BY percent_used DESC
                """,
                month,
            )
        return [dict(r) for r in rows]
