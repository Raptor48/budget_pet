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
                SELECT merchant_key, display_name, website,
                       created_at, updated_at
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
        display_name: Optional[str] = None,
        website: Optional[str] = None,
        chosen_logo_url: Optional[str] = None,
        chosen_logo_domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Set / replace the user override row for the merchant identified
        by the given Plaid attributes. Raises ``ValueError`` if no key can
        be derived.

        Both ``display_name`` (rename) and ``website`` are optional; the
        caller can update one without touching the other by passing only
        the field it cares about. ``None`` means "leave whatever's there
        unchanged"; the empty string ``""`` means "clear this field".

        If **both** ``merchant_entity_id`` and ``merchant_name`` are
        supplied we write **two** rows — ``eid:<id>`` and ``name:<lower(name)>``
        — sharing the same values. This is important because Plaid's
        recurring endpoint returns ``merchant_name`` only — no
        ``merchant_entity_id``. The name-keyed row is also a safety net
        for any statement-line variant where Plaid drops the entity id.

        When ``chosen_logo_url`` is provided, also upsert a corresponding
        row in ``merchant_logos`` with ``status='user_curated'`` so the
        read-time JOIN immediately renders the user's pick. We key
        ``merchant_logos`` on the user-facing merchant identifier
        (``merchant_name`` or the fallback display title) — the same
        expression the transactions repo's COALESCE join uses, so the
        two stay in lock-step.

        Returns the "preferred" alias row (eid-keyed when both keys
        exist, else name-keyed).
        """
        # Normalise inputs. Empty string is meaningful ("clear"); None
        # means "leave unchanged". We accept both via the same NULLIF
        # trick on the SQL side via the carry-current-value branch.
        display_clean: Optional[str] = None
        if display_name is not None:
            display_clean = display_name.strip()
        website_clean: Optional[str] = None
        if website is not None:
            website_clean = website.strip() or None  # empty → NULL

        if (
            display_name is None
            and website is None
            and chosen_logo_url is None
        ):
            raise ValueError(
                "Provide at least one of display_name, website, "
                "or chosen_logo_url"
            )

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
            secondary_key = f"name:{nm.lower()}"
        keys_to_write = [primary_key]
        if secondary_key and secondary_key != primary_key:
            keys_to_write.append(secondary_key)

        # The display_name column is NOT NULL with a non-empty CHECK in
        # the schema, so we can't write a row that only carries a
        # website without a name. For website-only edits, we read the
        # existing display_name from the primary key and keep it.
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Pre-read the existing primary row so we can carry
                # whichever field the caller didn't supply. This also
                # means a 'website-only' edit on a merchant that doesn't
                # have an alias yet must supply a display_name — we
                # surface that as the same ValueError as before.
                existing = await conn.fetchrow(
                    "SELECT display_name, website FROM merchant_aliases "
                    "WHERE merchant_key = $1",
                    primary_key,
                )
                merged_display = (
                    display_clean
                    if display_name is not None
                    else (existing["display_name"] if existing else None)
                )
                if not merged_display:
                    # Logo/website-only edit on a merchant with no prior
                    # alias: don't force the user to type a rename — fall
                    # back to the merchant's own label so the NOT NULL
                    # display_name is satisfied with a sensible value.
                    # ``nm`` is the raw merchant_name; ``fallback_display``
                    # is the original (pre-alias) display title the client
                    # passes as ``merchant_label``.
                    merged_display = nm or (fallback_display or "").strip()
                if not merged_display:
                    raise ValueError(
                        "display_name is required to create a merchant override"
                    )
                merged_website = (
                    website_clean
                    if website is not None
                    else (existing["website"] if existing else None)
                )

                primary_row = None
                for k in keys_to_write:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO merchant_aliases (merchant_key, display_name, website)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (merchant_key) DO UPDATE
                            SET display_name = EXCLUDED.display_name,
                                website      = EXCLUDED.website,
                                updated_at   = NOW()
                        RETURNING merchant_key, display_name, website,
                                  created_at, updated_at
                        """,
                        k,
                        merged_display,
                        merged_website,
                    )
                    if k == primary_key:
                        primary_row = row

                # Persist the logo pick (or clear an existing one) so
                # the read-time JOIN immediately reflects the user's
                # decision. Three cases:
                #
                #   1. chosen_logo_url is non-empty → upsert user_curated
                #   2. caller cleared the website (website=="") → drop
                #      the user_curated row so auto-enrichment can take
                #      over again on the next sync
                #   3. neither → leave logo state untouched
                #
                # The key for merchant_logos is the same expression the
                # transactions read-path JOINs on: merchant_name (when
                # Plaid provides it) else the display title fallback.
                logo_key = nm or (fallback_display or "").strip()
                if chosen_logo_url and logo_key:
                    await conn.execute(
                        """
                        INSERT INTO merchant_logos
                            (merchant_name, logo_url, brand_domain,
                             quality_score, status, miss_count,
                             refreshed_at)
                        VALUES ($1, $2, $3, 1.0,
                                'user_curated', 0, NOW())
                        ON CONFLICT (merchant_name) DO UPDATE SET
                            logo_url      = EXCLUDED.logo_url,
                            brand_domain  = EXCLUDED.brand_domain,
                            quality_score = 1.0,
                            status        = 'user_curated',
                            miss_count    = 0,
                            refreshed_at  = NOW()
                        """,
                        logo_key,
                        chosen_logo_url,
                        chosen_logo_domain or merged_website or "",
                    )
                elif website == "" and logo_key:
                    # Explicit clear: only drop the user_curated row;
                    # leave any prior auto-resolved entry alone (there
                    # rarely is one when a user override existed, but
                    # the principle is "only touch what the user owns").
                    await conn.execute(
                        "DELETE FROM merchant_logos "
                        "WHERE merchant_name = $1 AND status = 'user_curated'",
                        logo_key,
                    )

        assert primary_row is not None
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

        Also clears any ``user_curated`` row in ``merchant_logos`` for
        the same merchant — removing an alias is the user saying "drop
        my overrides for this merchant", which includes their picked
        logo. Auto-enrichment will re-evaluate on the next sync.
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
                # Drop the user_curated logo entry too — the logo key
                # is merchant_name (preferred) or the display fallback,
                # matching the upsert path above.
                logo_key = (merchant_name or "").strip() or (
                    fallback_display or ""
                ).strip()
                if logo_key:
                    await conn.execute(
                        "DELETE FROM merchant_logos "
                        "WHERE merchant_name = $1 AND status = 'user_curated'",
                        logo_key,
                    )
        return deleted > 0

    async def get_by_key(self, merchant_key: str) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT merchant_key, display_name, website,
                       created_at, updated_at
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
