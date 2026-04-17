"""
ReportsRepository — DB queries for all report endpoints + net worth snapshots.
"""
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from web.db import get_pool
from web.env_flags import reports_include_plaid_sandbox

logger = logging.getLogger(__name__)


def _sandbox_tx_filter(alias: str = "t") -> str:
    if reports_include_plaid_sandbox():
        return ""
    return f" AND ({alias}.source IS NULL OR {alias}.source <> 'plaid_sandbox')"


def _sandbox_tx_filter_no_alias() -> str:
    if reports_include_plaid_sandbox():
        return ""
    return " AND (source IS NULL OR source <> 'plaid_sandbox')"


def _private_tx_filter(alias: str = "t") -> str:
    """Return SQL fragment that hides private transactions from other users.
    Uses a subquery so callers don't need an explicit accounts JOIN.
    The $N placeholder for viewer_user_id must be appended to the query params list.
    Call as: _private_tx_filter("t")  →  " AND (NOT t.is_private OR ...)"
    The placeholder index must be supplied by the caller.
    """
    return (
        f" AND (NOT {alias}.is_private OR EXISTS ("
        f"SELECT 1 FROM accounts _pa WHERE _pa.id = {alias}.account_id AND _pa.user_id = %s))"
    )


def _private_tx_filter_with_idx(alias: str, idx: int) -> str:
    """Return SQL fragment using asyncpg-style $N placeholder."""
    return (
        f" AND (NOT {alias}.is_private OR EXISTS ("
        f"SELECT 1 FROM accounts _pa WHERE _pa.id = {alias}.account_id AND _pa.user_id = ${idx}))"
    )


class ReportsRepository:
    async def _pool(self):
        return await get_pool()

    async def get_cash_flow(self, month: str, viewer_user_id: Optional[int] = None) -> Dict[str, Any]:
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
                    COALESCE(SUM(CASE WHEN t.amount_cents < 0 THEN ABS(t.amount_cents) ELSE 0 END), 0) AS income_cents,
                    COALESCE(SUM(CASE WHEN t.amount_cents > 0 THEN t.amount_cents ELSE 0 END), 0) AS expenses_cents
                FROM transactions t
                WHERE COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                  AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                  {_sandbox_tx_filter("t")}
                  {private_filter}
                """,
                *params,
            )
        income = row["income_cents"] or 0
        expenses = row["expenses_cents"] or 0
        return {
            "month": month,
            "income_cents": income,
            "expenses_cents": expenses,
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
                    COALESCE(SUM(CASE WHEN t.amount_cents < 0 THEN ABS(t.amount_cents) ELSE 0 END), 0) AS income_cents,
                    COALESCE(SUM(CASE WHEN t.amount_cents > 0 THEN t.amount_cents ELSE 0 END), 0) AS expenses_cents
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
            income = r["income_cents"] or 0
            expenses = r["expenses_cents"] or 0
            result.append({
                "month": r["month"],
                "income_cents": income,
                "expenses_cents": expenses,
                "net_cents": income - expenses,
            })
        return result

    async def get_by_category(self, month: str, viewer_user_id: Optional[int] = None) -> List[Dict[str, Any]]:
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
                WITH actual AS (
                    SELECT t.category_id, SUM(t.amount_cents) AS amount_cents
                    FROM transactions t
                    WHERE t.amount_cents > 0
                      AND COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                      AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                      AND NOT EXISTS (SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id)
                      {_sandbox_tx_filter("t")}
                      {private_filter}
                    GROUP BY t.category_id

                    UNION ALL

                    SELECT ts.category_id, SUM(ts.amount_cents)
                    FROM transaction_splits ts
                    JOIN transactions t ON t.id = ts.parent_transaction_id
                    WHERE t.amount_cents > 0
                      AND COALESCE(t.authorized_date, t.date) >= ($1 || '-01')::date
                      AND COALESCE(t.authorized_date, t.date) < (($1 || '-01')::date + INTERVAL '1 month')
                      {_sandbox_tx_filter("t")}
                      {private_filter}
                    GROUP BY ts.category_id
                ),
                agg AS (
                    SELECT category_id, SUM(amount_cents) AS amount_cents
                    FROM actual
                    GROUP BY category_id
                ),
                total AS (SELECT SUM(amount_cents) AS total FROM agg)
                SELECT
                    agg.category_id,
                    COALESCE(c.name, 'Uncategorized') AS category_name,
                    agg.amount_cents,
                    CASE WHEN total.total > 0 THEN ROUND(agg.amount_cents::numeric / total.total * 100, 1) ELSE 0 END AS percent
                FROM agg
                CROSS JOIN total
                LEFT JOIN categories c ON c.id = agg.category_id
                ORDER BY agg.amount_cents DESC
                """,
                *params,
            )
        return [dict(r) for r in rows]

    async def get_by_tag(
        self, month: Optional[str] = None, tag_id: Optional[int] = None, viewer_user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        pool = await self._pool()
        conditions = ["t.amount_cents > 0"]
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
            "t.amount_cents > 0",
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
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    t.merchant_name,
                    MAX(t.logo_url) AS logo_url,
                    SUM(t.amount_cents) AS amount_cents,
                    COUNT(*) AS transaction_count
                FROM transactions t
                WHERE {where}
                GROUP BY t.merchant_name
                ORDER BY amount_cents DESC
                LIMIT ${idx}
                """,
                *params,
            )
        return [dict(r) for r in rows]

    async def get_net_worth(self) -> Dict[str, Any]:
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
        liquid = liquid or 0
        investments = investments or 0
        debt = debt or 0
        return {
            "liquid_cents": liquid,
            "investment_cents": investments,
            "debt_cents": debt,
            "net_worth_cents": liquid + investments - debt,
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
            liquid = liquid or 0
            investments = investments or 0
            debt = debt or 0
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

    async def get_financial_health_data(self) -> Dict[str, Any]:
        """Gather raw data needed for financial health score calculation."""
        pool = await self._pool()
        today = date.today()
        current_month = today.strftime("%Y-%m")
        async with pool.acquire() as conn:
            # Monthly income: average over the last 3 completed months.
            # Using only the current month produces an unreliable estimate early in the month.
            monthly_income = await conn.fetchval(
                f"""
                SELECT COALESCE(AVG(monthly_total), 0)
                FROM (
                    SELECT
                        TO_CHAR(COALESCE(authorized_date, date), 'YYYY-MM') AS m,
                        SUM(ABS(amount_cents)) AS monthly_total
                    FROM transactions
                    WHERE amount_cents < 0
                      AND COALESCE(authorized_date, date) >= (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '3 months')
                      AND COALESCE(authorized_date, date) < DATE_TRUNC('month', CURRENT_DATE)
                      {_sandbox_tx_filter_no_alias()}
                    GROUP BY m
                ) sub
                """
            )
            monthly_income = int(monthly_income or 0)
            # Monthly expenses: use the current month for the on-screen snapshot
            monthly_expenses = await conn.fetchval(
                f"""
                SELECT COALESCE(SUM(amount_cents), 0)
                FROM transactions
                WHERE amount_cents > 0
                  AND COALESCE(authorized_date, date) >= ($1 || '-01')::date
                  AND COALESCE(authorized_date, date) < (($1 || '-01')::date + INTERVAL '1 month')
                  {_sandbox_tx_filter_no_alias()}
                """,
                current_month,
            )
            # Average monthly expenses (last 6 months)
            avg_expenses = await conn.fetchval(
                f"""
                SELECT COALESCE(AVG(monthly_total), 0)
                FROM (
                    SELECT
                        TO_CHAR(COALESCE(authorized_date, date), 'YYYY-MM') AS m,
                        SUM(amount_cents) AS monthly_total
                    FROM transactions
                    WHERE amount_cents > 0
                      AND COALESCE(authorized_date, date) >= (CURRENT_DATE - INTERVAL '6 months')
                      {_sandbox_tx_filter_no_alias()}
                    GROUP BY m
                ) sub
                """
            )
            # Total debt (credit + loan)
            total_debt = await conn.fetchval(
                "SELECT COALESCE(SUM(current_balance_cents), 0) FROM accounts WHERE type IN ('credit','loan') AND is_active"
            )
            # Annual income estimate based on 3-month average (monthly * 12)
            annual_income = monthly_income * 12
            # Credit cards
            credit_limit = await conn.fetchval(
                "SELECT COALESCE(SUM(credit_limit_cents), 0) FROM accounts WHERE type = 'credit' AND is_active AND credit_limit_cents IS NOT NULL"
            )
            credit_balance = await conn.fetchval(
                "SELECT COALESCE(SUM(current_balance_cents), 0) FROM accounts WHERE type = 'credit' AND is_active"
            )
            # Liquid balance
            liquid = await conn.fetchval(
                "SELECT COALESCE(SUM(current_balance_cents), 0) FROM accounts WHERE type = 'depository' AND is_active"
            )
            # Overdue
            has_overdue = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM accounts WHERE is_overdue = TRUE AND is_active)"
            )
        return {
            "total_debt_cents": total_debt or 0,
            "annual_income_cents": annual_income,
            "monthly_income_cents": monthly_income,
            "monthly_expenses_cents": monthly_expenses or 0,
            "total_credit_limit_cents": credit_limit or 0,
            "total_credit_balance_cents": credit_balance or 0,
            "liquid_balance_cents": liquid or 0,
            "avg_monthly_expenses_cents": int(avg_expenses or 0),
            "has_overdue": bool(has_overdue),
        }
