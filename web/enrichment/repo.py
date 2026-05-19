"""``merchant_logos`` repository.

Single-table cache fronting Brandfetch's Brand Search response. Read
paths (``transactions/repo.py``, ``recurring/repo.py``) LEFT JOIN this
table and ``COALESCE(t.logo_url, ml.logo_url)`` so Plaid's licensed
logos always win when present and our Brandfetch fallback fills the
gaps.

Backoff strategy is in the read query (``names_to_enrich``) rather than
in Python so a single SQL plan picks the work for the next batch — no
race-y "fetch, sort, filter" loop in the orchestrator.

The ``merchant_name`` column is the natural primary key but it stores
*any* identifier that the transaction read-path can match on. For
transactions where Plaid populates ``merchant_name`` that's literally
that field; for transactions where ``merchant_name IS NULL`` but we
have a clean ``display_title`` (Zelle, Wells Fargo, ...), the display
title is what we cache under. The read-side JOIN does
``COALESCE(t.merchant_name, t.display_title)`` so both shapes resolve
to the same key.
"""

from __future__ import annotations

from typing import Optional

from web.db import get_pool
from web.transactions.display import _GENERIC_MERCHANT_NAMES


class MerchantLogosRepository:
    async def names_to_enrich(self, limit: int = 50) -> list[str]:
        """Return enrichment keys that need a Brandfetch lookup.

        A key qualifies when ALL of the following hold:

        1. It comes from a transaction with NULL/empty ``logo_url``
           (Plaid didn't enrich it). The key itself is
           ``COALESCE(merchant_name, display_title)`` — the same
           expression the read-path JOIN uses.
        2. Either there's no ``merchant_logos`` row yet, OR the existing
           row is unresolved and its backoff window has expired.
        3. The key isn't a generic single-word leak ("Online",
           "Mobile Recurring", ...). Brandfetch matches those to real
           but unrelated brands, so blocking at the query layer keeps
           junk logos out of the row UI entirely.

        Bank-noise patterns ("Payment from Maria", "Wire Fee", ...)
        are filtered in Python by the orchestrator before any Brandfetch
        call — keeping the SQL filter readable matters more than
        pushing every check down into the database.

        Backoff: starting from 1 day after the first miss, doubling each
        retry, capped at 30 days. Resolved rows are never re-fetched
        from this query — refreshes (logo rotation) are a separate
        admin-triggered code path, not in scope here.
        """
        pool = await get_pool()
        # ``_GENERIC_MERCHANT_NAMES`` is a frozenset; ``list(...)`` keeps
        # asyncpg's text[] binding happy and the SQL plan stable across
        # set iteration order.
        generic_lower = list(_GENERIC_MERCHANT_NAMES)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH candidates AS (
                    SELECT DISTINCT
                        COALESCE(NULLIF(merchant_name, ''),
                                 NULLIF(display_title, ''))
                            AS merchant_key
                    FROM transactions
                    WHERE (logo_url IS NULL OR logo_url = '')
                      AND COALESCE(NULLIF(merchant_name, ''),
                                   NULLIF(display_title, '')) IS NOT NULL
                )
                SELECT c.merchant_key
                FROM candidates c
                LEFT JOIN merchant_logos ml ON ml.merchant_name = c.merchant_key
                WHERE
                  LOWER(REGEXP_REPLACE(c.merchant_key, '\\s+', ' ', 'g'))
                      <> ALL($2::text[])
                  AND (
                    ml.merchant_name IS NULL
                    OR (
                        -- 'resolved' is sticky for the auto pipeline;
                        -- 'user_curated' is sticky forever (a manual
                        -- pick is never overwritten by auto-enrich).
                        ml.status NOT IN ('resolved', 'user_curated')
                        AND ml.refreshed_at < NOW() - LEAST(
                            INTERVAL '30 days',
                            POWER(2, ml.miss_count)::int * INTERVAL '1 day'
                        )
                    )
                  )
                ORDER BY c.merchant_key
                LIMIT $1
                """,
                limit,
                generic_lower,
            )
        return [r["merchant_key"] for r in rows]

    async def upsert_resolved(
        self,
        merchant_key: str,
        *,
        logo_url: str,
        brand_domain: str,
        quality_score: float,
        status: str = "resolved",
    ) -> None:
        """Mark a key as resolved with a real logo URL.

        Resets ``miss_count`` to 0 so a previously-failing lookup that
        finally hits doesn't carry the historical backoff into any
        future re-check we might add.

        ``status`` is parametrised so the Tier-1 (curated-map) and
        Tier-2 (search) paths can distinguish their results in the audit
        log. The schema check constraint accepts ``'resolved'``,
        ``'no_hit'``, ``'low_quality'``; either path uses ``'resolved'``
        for a successful save.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO merchant_logos
                    (merchant_name, logo_url, brand_domain, quality_score,
                     status, miss_count, refreshed_at)
                VALUES ($1, $2, $3, $4, $5, 0, NOW())
                ON CONFLICT (merchant_name) DO UPDATE SET
                    logo_url      = EXCLUDED.logo_url,
                    brand_domain  = EXCLUDED.brand_domain,
                    quality_score = EXCLUDED.quality_score,
                    status        = EXCLUDED.status,
                    miss_count    = 0,
                    refreshed_at  = NOW()
                """,
                merchant_key,
                logo_url,
                brand_domain,
                quality_score,
                status,
            )

    async def mark_miss(self, merchant_key: str, status: str) -> None:
        """Record a failed lookup so we don't retry on every sync.

        ``status`` ∈ {'no_hit', 'low_quality'} — the second covers the
        case where Brandfetch returned matches but none cleared the
        quality threshold. Storing them separately keeps the audit log
        useful when investigating why a brand isn't enriching.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO merchant_logos
                    (merchant_name, status, miss_count, refreshed_at)
                VALUES ($1, $2, 1, NOW())
                ON CONFLICT (merchant_name) DO UPDATE SET
                    status       = EXCLUDED.status,
                    miss_count   = merchant_logos.miss_count + 1,
                    refreshed_at = NOW()
                """,
                merchant_key,
                status,
            )

    async def get(self, merchant_key: str) -> Optional[dict]:
        """Diagnostic helper — fetch a single row by key. Not used by
        the read path (that JOINs in SQL) but handy for the audit-log
        and ad-hoc debugging.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM merchant_logos WHERE merchant_name = $1",
                merchant_key,
            )
        return dict(row) if row else None
