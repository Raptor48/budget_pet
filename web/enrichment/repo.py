"""``merchant_logos`` repository.

Single-table cache fronting Brandfetch's Brand Search response. Read
paths (``transactions/repo.py``, ``recurring/repo.py``) LEFT JOIN this
table and ``COALESCE(t.logo_url, ml.logo_url)`` so Plaid's licensed
logos always win when present and our Brandfetch fallback fills the
gaps.

Backoff strategy is in the read query (``names_to_enrich``) rather than
in Python so a single SQL plan picks the work for the next batch — no
race-y "fetch, sort, filter" loop in the orchestrator.
"""

from __future__ import annotations

from typing import Optional

from web.db import get_pool


class MerchantLogosRepository:
    async def names_to_enrich(self, limit: int = 50) -> list[str]:
        """Return merchant_names that need a Brandfetch lookup.

        A name qualifies when ALL of the following hold:

        1. It exists in ``transactions`` with a NULL/empty ``logo_url``
           (Plaid didn't enrich it).
        2. Either there's no ``merchant_logos`` row yet, OR the existing
           row is unresolved and its backoff window has expired.

        Backoff: starting from 1 day after the first miss, doubling each
        retry, capped at 30 days. Resolved rows are never re-fetched
        from this query — refreshes (logo rotation) are a separate
        admin-triggered code path, not in scope here.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH candidates AS (
                    SELECT DISTINCT merchant_name
                    FROM transactions
                    WHERE merchant_name IS NOT NULL
                      AND (logo_url IS NULL OR logo_url = '')
                )
                SELECT c.merchant_name
                FROM candidates c
                LEFT JOIN merchant_logos ml ON ml.merchant_name = c.merchant_name
                WHERE ml.merchant_name IS NULL
                   OR (ml.status <> 'resolved'
                       AND ml.refreshed_at < NOW() - LEAST(
                           INTERVAL '30 days',
                           POWER(2, ml.miss_count)::int * INTERVAL '1 day'
                       ))
                ORDER BY c.merchant_name
                LIMIT $1
                """,
                limit,
            )
        return [r["merchant_name"] for r in rows]

    async def upsert_resolved(
        self,
        merchant_name: str,
        *,
        logo_url: str,
        brand_domain: str,
        quality_score: float,
    ) -> None:
        """Mark a merchant as resolved with a real logo URL.

        Resets ``miss_count`` to 0 so a previously-failing lookup that
        finally hits doesn't carry the historical backoff into any
        future re-check we might add.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO merchant_logos
                    (merchant_name, logo_url, brand_domain, quality_score,
                     status, miss_count, refreshed_at)
                VALUES ($1, $2, $3, $4, 'resolved', 0, NOW())
                ON CONFLICT (merchant_name) DO UPDATE SET
                    logo_url      = EXCLUDED.logo_url,
                    brand_domain  = EXCLUDED.brand_domain,
                    quality_score = EXCLUDED.quality_score,
                    status        = 'resolved',
                    miss_count    = 0,
                    refreshed_at  = NOW()
                """,
                merchant_name,
                logo_url,
                brand_domain,
                quality_score,
            )

    async def mark_miss(self, merchant_name: str, status: str) -> None:
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
                merchant_name,
                status,
            )

    async def get(self, merchant_name: str) -> Optional[dict]:
        """Diagnostic helper — fetch a single row by merchant_name. Not
        used by the read path (that JOINs in SQL) but handy for the
        audit-log and ad-hoc debugging.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM merchant_logos WHERE merchant_name = $1",
                merchant_name,
            )
        return dict(row) if row else None
