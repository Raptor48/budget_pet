"""User-defined merchant → category rules applied during Plaid import."""
from __future__ import annotations

from typing import Optional

from web.db import get_pool


def _merchant_key(merchant_entity_id: Optional[str], merchant_name: Optional[str]) -> Optional[str]:
    eid = (merchant_entity_id or "").strip()
    if eid:
        return f"eid:{eid.lower()}"
    name = (merchant_name or "").strip()
    if name:
        return f"name:{name.lower()}"
    return None


class MerchantRulesRepository:
    async def _pool(self):
        return await get_pool()

    async def lookup_category(
        self,
        user_id: int,
        merchant_entity_id: Optional[str],
        merchant_name: Optional[str],
    ) -> Optional[int]:
        key = _merchant_key(merchant_entity_id, merchant_name)
        if not key:
            return None
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT category_id FROM merchant_category_rules WHERE user_id = $1 AND merchant_key = $2",
                user_id,
                key,
            )
        return int(row["category_id"]) if row else None

    async def upsert_rule(self, user_id: int, merchant_entity_id: Optional[str], merchant_name: Optional[str], category_id: int) -> dict:
        key = _merchant_key(merchant_entity_id, merchant_name)
        if not key:
            raise ValueError("merchant_entity_id or merchant_name required")
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO merchant_category_rules (user_id, merchant_key, category_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, merchant_key) DO UPDATE SET category_id = EXCLUDED.category_id
                RETURNING id, merchant_key, category_id
                """,
                user_id,
                key,
                category_id,
            )
            cat = await conn.fetchrow("SELECT name FROM categories WHERE id = $1", row["category_id"])
        return {"id": row["id"], "merchant_key": row["merchant_key"], "category_id": row["category_id"], "category_name": cat["name"]}

    async def list_rules(self, user_id: int) -> list[dict]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.id, r.merchant_key, r.category_id, c.name AS category_name
                FROM merchant_category_rules r
                JOIN categories c ON c.id = r.category_id
                WHERE r.user_id = $1
                ORDER BY r.merchant_key
                """,
                user_id,
            )
        return [dict(x) for x in rows]

    async def delete_rule(self, user_id: int, rule_id: int) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            r = await conn.execute(
                "DELETE FROM merchant_category_rules WHERE id = $1 AND user_id = $2",
                rule_id,
                user_id,
            )
        return r != "DELETE 0"
