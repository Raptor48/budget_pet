"""
AccountsRepository — all DB operations for the accounts table.
Uses the shared asyncpg pool from web.db.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from web.accounts.cash_wallet import (
    CASH_WALLET_NAME,
    CASH_WALLET_SUBTYPE,
    CASH_WALLET_TYPE,
    is_designated_cash_wallet,
)
from web.db import get_pool

logger = logging.getLogger(__name__)


class AccountsRepository:
    async def _pool(self):
        return await get_pool()

    _SELECT_WITH_BRANDING = """
        SELECT
            a.*,
            pi.institution_logo,
            pi.institution_color,
            u.username AS owner_username
        FROM accounts a
        LEFT JOIN plaid_items pi ON a.plaid_item_id = pi.item_id
        LEFT JOIN users u ON a.user_id = u.id
    """

    async def list_accounts(self, active_only: bool = True) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            if active_only:
                rows = await conn.fetch(
                    self._SELECT_WITH_BRANDING + "WHERE a.is_active = TRUE ORDER BY a.type, a.name"
                )
            else:
                rows = await conn.fetch(
                    self._SELECT_WITH_BRANDING + "ORDER BY a.type, a.name"
                )
        out = [dict(r) for r in rows]
        for d in out:
            d["is_cash_wallet"] = is_designated_cash_wallet(d)
        return out

    async def get_account(self, account_id: int) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                self._SELECT_WITH_BRANDING + "WHERE a.id = $1",
                account_id,
            )
        if not row:
            return None
        d = dict(row)
        d["is_cash_wallet"] = is_designated_cash_wallet(d)
        return d

    async def ensure_cash_wallet(self, user_id: int) -> Dict[str, Any]:
        """
        One manual depository 'Cash' account per user (no plaid_account_id).
        Uses a transaction-scoped advisory lock to avoid duplicate rows under concurrency.
        """
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock((abs(hashtext('budget_pet_cash_wallet:' || $1::text)))::bigint)",
                    str(user_id),
                )
                existing = await conn.fetchrow(
                    """
                    SELECT a.id FROM accounts a
                    WHERE a.user_id = $1
                      AND a.plaid_account_id IS NULL
                      AND a.name = $2
                      AND a.type = $3
                      AND COALESCE(a.subtype, '') = $4
                      AND a.is_active = TRUE
                    LIMIT 1
                    """,
                    user_id,
                    CASH_WALLET_NAME,
                    CASH_WALLET_TYPE,
                    CASH_WALLET_SUBTYPE,
                )
                if existing:
                    aid = existing["id"]
                else:
                    ins = await conn.fetchrow(
                        """
                        INSERT INTO accounts (
                            plaid_account_id, plaid_item_id, name, official_name, mask,
                            type, subtype, current_balance_cents, available_balance_cents,
                            credit_limit_cents, currency, holder_category, user_id, is_active
                        ) VALUES (
                            NULL, NULL, $1, NULL, NULL,
                            $2, $3, 0, NULL, NULL, 'USD', NULL, $4, TRUE
                        )
                        RETURNING id
                        """,
                        CASH_WALLET_NAME,
                        CASH_WALLET_TYPE,
                        CASH_WALLET_SUBTYPE,
                        user_id,
                    )
                    aid = ins["id"]
                row = await conn.fetchrow(
                    self._SELECT_WITH_BRANDING + "WHERE a.id = $1",
                    aid,
                )
        d = dict(row)
        d["is_cash_wallet"] = True
        return d

    async def get_by_plaid_id(self, plaid_account_id: str) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM accounts WHERE plaid_account_id = $1", plaid_account_id
            )
        return dict(row) if row else None

    async def create_account(self, data: Dict[str, Any]) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO accounts (
                    plaid_account_id, plaid_item_id, name, official_name, mask,
                    type, subtype, current_balance_cents, available_balance_cents,
                    credit_limit_cents, currency, holder_category, is_active
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                RETURNING *
                """,
                data.get("plaid_account_id"),
                data.get("plaid_item_id"),
                data["name"],
                data.get("official_name"),
                data.get("mask"),
                data["type"],
                data.get("subtype"),
                data.get("current_balance_cents", 0),
                data.get("available_balance_cents"),
                data.get("credit_limit_cents"),
                data.get("currency", "USD"),
                data.get("holder_category"),
                data.get("is_active", True),
            )
        d = dict(row)
        d["is_cash_wallet"] = is_designated_cash_wallet(d)
        return d

    async def update_account(self, account_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Partial update — only keys present in data are changed."""
        allowed = {
            "name", "official_name", "mask", "type", "subtype",
            "current_balance_cents", "available_balance_cents", "credit_limit_cents",
            "apr_percent", "min_payment_cents", "due_day", "is_overdue",
            "last_payment_date", "last_statement_balance_cents", "expected_payoff_date",
            "ytd_interest_paid_cents", "currency", "holder_category", "is_active",
            "last_synced_at", "user_id",
        }
        fields = {k: v for k, v in data.items() if k in allowed}
        if not fields:
            return await self.get_account(account_id)

        set_clause = ", ".join(
            f"{col} = ${i + 2}" for i, col in enumerate(fields.keys())
        )
        values = list(fields.values())

        pool = await self._pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE accounts SET {set_clause}, updated_at = NOW() WHERE id = $1",
                account_id,
                *values,
            )
            if result == "UPDATE 0":
                return None
        return await self.get_account(account_id)

    async def delete_account(self, account_id: int) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE accounts SET is_active = FALSE, updated_at = NOW() WHERE id = $1",
                account_id,
            )
        return result != "UPDATE 0"

    async def provision_from_plaid(
        self, plaid_accounts: List[Dict[str, Any]], plaid_item_id: str
    ) -> int:
        """
        Upsert accounts from Plaid /accounts/balance/get response.
        Returns count of new accounts created.
        """
        created = 0
        pool = await self._pool()
        async with pool.acquire() as conn:
            # Inherit owner from the Plaid item that owns these accounts
            item_row = await conn.fetchrow(
                "SELECT user_id FROM plaid_items WHERE item_id = $1", plaid_item_id
            )
            item_user_id = item_row["user_id"] if item_row else None

            for acct in plaid_accounts:
                plaid_id = acct.get("account_id", "")
                if not plaid_id:
                    continue
                balances = acct.get("balances") or {}
                current = balances.get("current")
                available = balances.get("available")
                limit_ = balances.get("limit")
                currency = balances.get("iso_currency_code") or "USD"
                current_cents = int(round(current * 100)) if current is not None else 0
                available_cents = int(round(available * 100)) if available is not None else None
                limit_cents = int(round(limit_ * 100)) if limit_ is not None else None

                existing = await conn.fetchrow(
                    "SELECT id FROM accounts WHERE plaid_account_id = $1", plaid_id
                )
                if existing:
                    await conn.execute(
                        """
                        UPDATE accounts SET
                            name = $2, official_name = $3, mask = $4,
                            type = $5, subtype = $6,
                            current_balance_cents = $7,
                            available_balance_cents = $8,
                            credit_limit_cents = $9,
                            currency = $10,
                            holder_category = $11,
                            user_id = COALESCE(accounts.user_id, $12),
                            last_synced_at = NOW(),
                            updated_at = NOW()
                        WHERE plaid_account_id = $1
                        """,
                        plaid_id,
                        acct.get("name", ""),
                        acct.get("official_name"),
                        acct.get("mask"),
                        acct.get("type", "other"),
                        acct.get("subtype"),
                        current_cents,
                        available_cents,
                        limit_cents,
                        currency,
                        acct.get("holder_category"),
                        item_user_id,
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO accounts (
                            plaid_account_id, plaid_item_id, name, official_name, mask,
                            type, subtype, current_balance_cents, available_balance_cents,
                            credit_limit_cents, currency, holder_category, user_id, is_active
                        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,TRUE)
                        ON CONFLICT (plaid_account_id) DO NOTHING
                        """,
                        plaid_id,
                        plaid_item_id,
                        acct.get("name", ""),
                        acct.get("official_name"),
                        acct.get("mask"),
                        acct.get("type", "other"),
                        acct.get("subtype"),
                        current_cents,
                        available_cents,
                        limit_cents,
                        currency,
                        acct.get("holder_category"),
                        item_user_id,
                    )
                    created += 1
        return created
