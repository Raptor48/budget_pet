"""
SplitsRepository — handles transaction_splits CRUD.

Invariant: SUM(splits.amount_cents) == parent.amount_cents.
This invariant is enforced in set_splits().
"""
import logging
from typing import Any, Dict, List, Optional

from web.db import get_pool

logger = logging.getLogger(__name__)


class SplitsRepository:
    async def _pool(self):
        return await get_pool()

    async def get_splits(self, transaction_id: int) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM transaction_splits WHERE parent_transaction_id = $1 ORDER BY id",
                transaction_id,
            )
        return [dict(r) for r in rows]

    async def set_splits(
        self, transaction_id: int, splits: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Replace all existing splits for a transaction.
        Validates that SUM(amount_cents) == parent.amount_cents.
        Raises ValueError on invariant violation.
        """
        pool = await self._pool()
        async with pool.acquire() as conn:
            parent = await conn.fetchrow(
                "SELECT amount_cents FROM transactions WHERE id = $1", transaction_id
            )
            if not parent:
                raise ValueError("Transaction not found")

            total = sum(s["amount_cents"] for s in splits)
            if total != parent["amount_cents"]:
                raise ValueError(
                    f"Split total {total} does not match transaction amount {parent['amount_cents']}"
                )

            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM transaction_splits WHERE parent_transaction_id = $1",
                    transaction_id,
                )
                rows = []
                for s in splits:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO transaction_splits
                            (parent_transaction_id, category_id, tag_id, amount_cents, note)
                        VALUES ($1,$2,$3,$4,$5)
                        RETURNING *
                        """,
                        transaction_id,
                        s.get("category_id"),
                        s.get("tag_id"),
                        s["amount_cents"],
                        s.get("note"),
                    )
                    rows.append(dict(row))
        return rows

    async def delete_splits(self, transaction_id: int) -> int:
        pool = await self._pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM transaction_splits WHERE parent_transaction_id = $1",
                transaction_id,
            )
        count_str = result.split()[-1] if result else "0"
        return int(count_str) if count_str.isdigit() else 0
