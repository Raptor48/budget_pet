"""User-defined merchant → category rules applied during Plaid import (family-wide).

Rules can optionally be **narrowed by description substring**. The same
``merchant_key`` can have:

* a generic rule (``description_contains IS NULL``) — fires on every
  transaction with that ``merchant_key``; this is the original behavior,
  unchanged for users who don't touch the new field, and
* one or more **narrow** rules with a non-NULL ``description_contains``
  — fire only when the transaction's ``name`` (statement line) or
  ``display_title`` contains the substring (case-insensitive).

When both kinds exist for the same merchant the narrow rule wins. The
SQL ``ORDER BY description_contains IS NULL`` puts ``FALSE`` (i.e.
"specific") before ``TRUE`` ("generic"), so ``LIMIT 1`` returns the
specific match. See ``docs/categorization-precedence.md`` §3 for the
full design rationale.
"""
from __future__ import annotations

from typing import List, Optional

from web.db import get_pool

from .keys import display_merchant_label, merchant_key as build_merchant_key


def _normalize_filter(value: Optional[str]) -> Optional[str]:
    """Lower-case and strip a description filter, returning ``None`` for blanks.

    Blank → NULL keeps the schema clean: a rule that the user "added a
    filter to and then cleared it" is exactly the same as a rule with no
    filter at all, so we don't proliferate empty-string rows.
    """
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


class MerchantRulesRepository:
    async def _pool(self):
        return await get_pool()

    async def lookup_category(
        self,
        merchant_entity_id: Optional[str],
        merchant_name: Optional[str],
        fallback_display: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[int]:
        """
        Resolve ``category_id`` from a saved rule matching this transaction.

        ``description`` is the candidate text checked against
        ``description_contains``. Pass the transaction's ``name`` (raw
        statement line) joined with ``display_title`` (normalized form) so
        substring matches work whether the user typed the substring as it
        appears in the bank statement or as it appears in our cleaned-up UI
        title. Pass ``None`` to skip narrow rules entirely.

        ``fallback_display`` is used when neither a Plaid merchant entity id
        nor a merchant name is available (ACH / checks / bill pays). It
        should be the transaction's normalized ``display_title``.
        """
        key = build_merchant_key(merchant_entity_id, merchant_name, fallback_display)
        if not key:
            return None
        # Lower-case the candidate text once on the Python side; the SQL
        # already stores ``description_contains`` lower-cased, so the
        # comparison is a simple LIKE without per-row case folding.
        haystack = (description or "").lower()
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT category_id
                FROM merchant_category_rules
                WHERE merchant_key = $1
                  AND (
                      description_contains IS NULL
                      OR ($2::text <> '' AND position(description_contains IN $2::text) > 0)
                  )
                ORDER BY description_contains IS NULL  -- FALSE (specific) before TRUE (generic)
                LIMIT 1
                """,
                key,
                haystack,
            )
        return int(row["category_id"]) if row else None

    async def upsert_rule(
        self,
        merchant_entity_id: Optional[str],
        merchant_name: Optional[str],
        category_id: int,
        fallback_display: Optional[str] = None,
        description_contains: Optional[str] = None,
    ) -> dict:
        """Create or replace a rule.

        Uniqueness is on ``(merchant_key, COALESCE(description_contains, ''))``,
        so the same merchant can carry both a generic and one or more
        description-filtered rules. Re-PUT-ing with the same pair updates
        the ``category_id``.
        """
        key = build_merchant_key(merchant_entity_id, merchant_name, fallback_display)
        if not key:
            raise ValueError("merchant_entity_id, merchant_name, or merchant_label required")
        filt = _normalize_filter(description_contains)
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO merchant_category_rules (merchant_key, category_id, description_contains)
                VALUES ($1, $2, $3)
                ON CONFLICT (merchant_key, COALESCE(description_contains, '')) DO UPDATE SET
                    category_id = EXCLUDED.category_id
                RETURNING id, merchant_key, category_id, description_contains
                """,
                key,
                category_id,
                filt,
            )
            cat = await conn.fetchrow("SELECT name FROM categories WHERE id = $1", row["category_id"])
        label = display_merchant_label(row["merchant_key"])
        return {
            "id": row["id"],
            "merchant_key": row["merchant_key"],
            "category_id": row["category_id"],
            "category_name": cat["name"],
            "display_label": label,
            "description_contains": row["description_contains"],
        }

    async def list_rules(self) -> List[dict]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.id, r.merchant_key, r.category_id, r.description_contains,
                       c.name AS category_name
                FROM merchant_category_rules r
                JOIN categories c ON c.id = r.category_id
                ORDER BY r.merchant_key, r.description_contains NULLS LAST
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
                SELECT r.id, r.merchant_key, r.category_id, r.description_contains,
                       c.name AS category_name
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
