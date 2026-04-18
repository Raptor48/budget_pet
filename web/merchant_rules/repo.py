"""User-defined merchant → category rules applied during Plaid import (family-wide)."""
from __future__ import annotations

from typing import Optional

from web.db import get_pool

from .keys import display_merchant_label, merchant_key as build_merchant_key


class MerchantRulesRepository:
    async def _pool(self):
        return await get_pool()

    async def lookup_category(
        self,
        merchant_entity_id: Optional[str],
        merchant_name: Optional[str],
        fallback_display: Optional[str] = None,
    ) -> Optional[int]:
        """
        Resolve ``category_id`` from a saved rule matching this transaction.

        ``fallback_display`` is used when neither a Plaid merchant entity id
        nor a merchant name is available (ACH / checks / bill pays). It should
        be the transaction's normalized ``display_title``.
        """
        key = build_merchant_key(merchant_entity_id, merchant_name, fallback_display)
        if not key:
            return None
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT category_id FROM merchant_category_rules WHERE merchant_key = $1",
                key,
            )
        return int(row["category_id"]) if row else None

    async def upsert_rule(
        self,
        merchant_entity_id: Optional[str],
        merchant_name: Optional[str],
        category_id: int,
        fallback_display: Optional[str] = None,
    ) -> dict:
        key = build_merchant_key(merchant_entity_id, merchant_name, fallback_display)
        if not key:
            raise ValueError("merchant_entity_id, merchant_name, or merchant_label required")
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO merchant_category_rules (merchant_key, category_id)
                VALUES ($1, $2)
                ON CONFLICT (merchant_key) DO UPDATE SET category_id = EXCLUDED.category_id
                RETURNING id, merchant_key, category_id
                """,
                key,
                category_id,
            )
            cat = await conn.fetchrow("SELECT name FROM categories WHERE id = $1", row["category_id"])
        label = display_merchant_label(row["merchant_key"])
        return {
            "id": row["id"],
            "merchant_key": row["merchant_key"],
            "category_id": row["category_id"],
            "category_name": cat["name"],
            "display_label": label,
        }

    async def list_rules(self) -> list[dict]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.id, r.merchant_key, r.category_id, c.name AS category_name
                FROM merchant_category_rules r
                JOIN categories c ON c.id = r.category_id
                ORDER BY r.merchant_key
                """,
            )
        out = []
        for x in rows:
            d = dict(x)
            d["display_label"] = display_merchant_label(d["merchant_key"])
            out.append(d)
        return out

    async def get_rule(self, rule_id: int) -> Optional[dict]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT r.id, r.merchant_key, r.category_id, c.name AS category_name
                FROM merchant_category_rules r
                JOIN categories c ON c.id = r.category_id
                WHERE r.id = $1
                """,
                rule_id,
            )
        if not row:
            return None
        d = dict(row)
        d["display_label"] = display_merchant_label(d["merchant_key"])
        return d

    async def delete_rule(self, rule_id: int) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            r = await conn.execute(
                "DELETE FROM merchant_category_rules WHERE id = $1",
                rule_id,
            )
        return r != "DELETE 0"
