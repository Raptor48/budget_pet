"""Per-merchant display rename (alias).

Plaid surfaces every merchant under a fixed Plaid-derived label
(``merchant_name``); this module lets the household pick a friendlier name
for that merchant without modifying the underlying transaction or affecting
categorization, merchant_key matching, math, or Plaid sync.

The alias is keyed on ``merchant_key`` — the same family-global identifier
that drives ``merchant_category_rules`` (see ``web/merchant_rules/keys.py``).
That means a single alias row covers every transaction Plaid attributes to
the same merchant, regardless of statement-line cosmetics (trailing store
numbers, dates, POS suffix, etc.).

Read-side application is centralized via ``alias_join_sql(t)``: every repo
that returns merchant-bearing rows (transactions, recurring streams, top
merchants) wraps its query with this LEFT JOIN and ``COALESCE`` the alias
into the outgoing ``display_title`` (or grouping key, for top merchants).
``display_title`` stays auto-normalized in the ``transactions`` table — the
alias is layered on read so renames apply instantly to **all** historical
rows without a backfill UPDATE.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from web.db import get_pool

from .keys import display_merchant_label, merchant_key as build_merchant_key


# ---------------------------------------------------------------------------
# SQL helper — single source of truth for the JOIN clause
# ---------------------------------------------------------------------------

def alias_join_sql(table_alias: str = "t", join_alias: str = "ma") -> str:
    """Return a ``LEFT JOIN merchant_aliases <ma> ON ...`` clause that mirrors
    the Python ``merchant_key()`` precedence in SQL.

    The clause assumes the source table exposes ``merchant_entity_id``,
    ``merchant_name``, and (optionally) ``display_title`` columns. ``transactions``
    and ``recurring_streams`` both satisfy this contract.

    Returned columns to read after the join:

      * ``<ma>.display_name`` — the user's chosen rename (NULL when no alias).
      * ``<ma>.merchant_key`` — the resolved alias key (also NULL when no alias).

    The ``COALESCE(<ma>.display_name, <table_alias>.display_title)`` pattern
    is the one all callers should use to surface the effective title in the
    response. Grouping queries (top merchants) should ``GROUP BY`` the same
    expression so aliased rows aggregate under the chosen name.
    """
    t = table_alias
    ja = join_alias
    return f"""
        LEFT JOIN merchant_aliases {ja} ON {ja}.merchant_key = (
            CASE
                WHEN NULLIF(TRIM({t}.merchant_entity_id), '') IS NOT NULL
                    THEN 'eid:' || lower({t}.merchant_entity_id)
                WHEN NULLIF(TRIM({t}.merchant_name), '') IS NOT NULL
                    THEN 'name:' || lower({t}.merchant_name)
                ELSE 'name:' || lower(COALESCE({t}.display_title, ''))
            END
        )
    """.strip()


# ---------------------------------------------------------------------------
# Repo
# ---------------------------------------------------------------------------

class MerchantAliasesRepository:
    async def _pool(self):
        return await get_pool()

    async def list_aliases(self) -> List[Dict[str, Any]]:
        """Return every alias with the human-readable label of its key."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT merchant_key, display_name, created_at, updated_at
                FROM merchant_aliases
                ORDER BY display_name
                """,
            )
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["display_label"] = display_merchant_label(d["merchant_key"])
            out.append(d)
        return out

    async def upsert_alias(
        self,
        *,
        merchant_entity_id: Optional[str],
        merchant_name: Optional[str],
        fallback_display: Optional[str],
        display_name: str,
    ) -> Dict[str, Any]:
        """Set / replace the alias for the merchant identified by the given
        Plaid attributes. Raises ``ValueError`` if no key can be derived.

        If **both** ``merchant_entity_id`` and ``merchant_name`` are supplied
        we write **two** rows — ``eid:<id>`` and ``name:<lower(name)>`` — with
        the same ``display_name``. This is important because Plaid's recurring
        endpoint (``/transactions/recurring/get``) returns ``merchant_name``
        only — no ``merchant_entity_id``. Without the redundant ``name:`` row
        the alias would silently fail to match recurring stream rows of the
        same merchant. The name-keyed row is also a safety net for any
        statement-line variant where Plaid drops the entity id.

        The "preferred" key (the one matched first by ``merchant_key()``,
        i.e. ``eid:`` when present, else ``name:``) is the one returned in
        the response so the UI can use it as the canonical identifier for
        delete / update.
        """
        cleaned = (display_name or "").strip()
        if not cleaned:
            raise ValueError("display_name cannot be empty")
        primary_key = build_merchant_key(
            merchant_entity_id, merchant_name, fallback_display
        )
        if not primary_key:
            raise ValueError(
                "merchant_entity_id, merchant_name, or fallback_display required"
            )
        secondary_key: Optional[str] = None
        eid = (merchant_entity_id or "").strip()
        nm = (merchant_name or "").strip()
        if eid and nm:
            # primary is "eid:..."; also write "name:..." as a fallback alias.
            secondary_key = f"name:{nm.lower()}"
        keys_to_write = [primary_key]
        if secondary_key and secondary_key != primary_key:
            keys_to_write.append(secondary_key)
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                primary_row = None
                for k in keys_to_write:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO merchant_aliases (merchant_key, display_name)
                        VALUES ($1, $2)
                        ON CONFLICT (merchant_key) DO UPDATE
                            SET display_name = EXCLUDED.display_name,
                                updated_at   = NOW()
                        RETURNING merchant_key, display_name, created_at, updated_at
                        """,
                        k,
                        cleaned,
                    )
                    if k == primary_key:
                        primary_row = row
        assert primary_row is not None  # primary_key is always written first
        d = dict(primary_row)
        d["display_label"] = display_merchant_label(d["merchant_key"])
        return d

    async def delete_alias(
        self,
        *,
        merchant_entity_id: Optional[str] = None,
        merchant_name: Optional[str] = None,
        fallback_display: Optional[str] = None,
        merchant_key: Optional[str] = None,
    ) -> bool:
        """Remove an alias. Pass ``merchant_key`` (single-row delete — useful
        from the Settings list) **or** the Plaid attribute trio (twin-row
        delete — clears both ``eid:`` and ``name:`` rows written by
        ``upsert_alias``). Returns True if at least one row was removed.
        """
        keys: List[str] = []
        if merchant_key:
            keys.append(merchant_key)
        else:
            primary = build_merchant_key(
                merchant_entity_id, merchant_name, fallback_display
            )
            if primary:
                keys.append(primary)
            eid = (merchant_entity_id or "").strip()
            nm = (merchant_name or "").strip()
            if eid and nm:
                secondary = f"name:{nm.lower()}"
                if secondary not in keys:
                    keys.append(secondary)
        if not keys:
            return False
        pool = await self._pool()
        deleted = 0
        async with pool.acquire() as conn:
            async with conn.transaction():
                for k in keys:
                    result = await conn.execute(
                        "DELETE FROM merchant_aliases WHERE merchant_key = $1",
                        k,
                    )
                    if result != "DELETE 0":
                        deleted += 1
        return deleted > 0

    async def get_by_key(self, merchant_key: str) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT merchant_key, display_name, created_at, updated_at
                FROM merchant_aliases
                WHERE merchant_key = $1
                """,
                merchant_key,
            )
        if not row:
            return None
        d = dict(row)
        d["display_label"] = display_merchant_label(d["merchant_key"])
        return d
