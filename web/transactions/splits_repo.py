"""
SplitsRepository — handles transaction_splits CRUD.

Invariant: SUM(splits.amount_cents) == parent.amount_cents.
This invariant is enforced in set_splits().
"""
import logging
from typing import Any, Dict, List

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

            # Single atomic round-trip: DELETE existing + bulk INSERT via
            # UNNEST'd arrays. The original implementation issued one
            # ``await conn.fetchrow`` per split inside the transaction —
            # which held a row-level lock on every newly-inserted split
            # plus an FK-validation lock on the parent ``transactions``
            # row for the duration of the whole loop. Whenever anything
            # else touched the same parent (Plaid upsert ON CONFLICT,
            # the shared-expense matcher's ``_assign_to_shared`` UPDATE,
            # or even a concurrent user editing the same row in a second
            # tab) the per-row INSERTs queued behind it and tripped the
            # pool's 30s ``command_timeout`` — surfaced as "Load failed"
            # in the UI. Same lesson as the bulk-unsubscribe fix: turn
            # the loop into one statement.
            ids: List[int] = [transaction_id] * len(splits)
            category_ids: List[Any] = [s.get("category_id") for s in splits]
            tag_ids: List[Any] = [s.get("tag_id") for s in splits]
            amounts: List[int] = [int(s["amount_cents"]) for s in splits]
            notes: List[Any] = [s.get("note") for s in splits]
            counterparties: List[Any] = [s.get("counterparty") for s in splits]
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM transaction_splits WHERE parent_transaction_id = $1",
                    transaction_id,
                )
                inserted = await conn.fetch(
                    """
                    INSERT INTO transaction_splits
                        (parent_transaction_id, category_id, tag_id,
                         amount_cents, note, counterparty)
                    SELECT * FROM UNNEST(
                        $1::int[], $2::int[], $3::int[],
                        $4::bigint[], $5::text[], $6::text[]
                    )
                    RETURNING *
                    """,
                    ids,
                    category_ids,
                    tag_ids,
                    amounts,
                    notes,
                    counterparties,
                )
                # asyncpg returns rows in INSERT order; preserve that so
                # the UI's order-matters splits (auto-balance row 1, etc.)
                # round-trip the same way the user saw them.
                rows = [dict(r) for r in inserted]
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
