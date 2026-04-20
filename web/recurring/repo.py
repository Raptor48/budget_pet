"""
RecurringRepository — DB operations for recurring_streams.
Handles upsert from Plaid /transactions/recurring/get response,
price change detection (threshold 10%), and user label updates.
"""
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from web.accounts.repo import AccountsRepository
from web.categories.pfc_display import format_plaid_category_for_display
from web.db import get_pool
from web.transactions.display import normalize_transaction_title

logger = logging.getLogger(__name__)

PRICE_CHANGE_THRESHOLD = 0.10  # 10%


def _coerce_last_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def _sort_streams_by_next_payment(rows: List[Dict[str, Any]]) -> None:
    """In-place: soonest next payment first (``next_occurrence`` rules); unknown last."""
    # Local import avoids import cycle: reports.routes imports this repo.
    from web.reports.calculations import next_occurrence

    def sort_key(row: Dict[str, Any]) -> tuple:
        last_d = _coerce_last_date(row.get("last_date"))
        freq = (row.get("frequency") or "").strip()
        if not last_d or not freq:
            return (1, date.max, row.get("id") or 0)
        nxt = next_occurrence(last_d, freq)
        if nxt is None:
            return (1, date.max, row.get("id") or 0)
        return (0, nxt, row.get("id") or 0)

    rows.sort(key=sort_key)


class RecurringRepository:
    async def _pool(self):
        return await get_pool()

    async def list_streams(
        self,
        direction: Optional[str] = None,
        active_only: bool = True,
        viewer_user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """List recurring streams, enriched with account + owner + primary
        category metadata so the UI can render "Charged to <card · @owner>"
        and a collapsed "Category" column without N+1 follow-up fetches.

        The returned dict follows `RecurringStreamOut`'s enrichment contract:
        `account_name`, `account_mask`, `owner_username`,
        `primary_category_{id,name,color}`, and `display_title`.

        When ``viewer_user_id`` is set (e.g. Insights), streams whose underlying
        account is owned by a *different* user are filtered out. Shared accounts
        (``accounts.user_id IS NULL``) remain visible. ``GET /api/recurring``
        passes ``viewer_user_id=None`` for a single household-wide list.

        Results are sorted by computed next payment date (``next_occurrence``),
        soonest first; rows without a computable next date sort last.
        """
        pool = await self._pool()
        conditions: List[str] = []
        params: List[Any] = []
        idx = 1
        if direction:
            conditions.append(f"rs.direction = ${idx}")
            params.append(direction)
            idx += 1
        if active_only:
            conditions.append("rs.is_active = TRUE")
        if viewer_user_id is not None:
            conditions.append(f"(a.user_id = ${idx} OR a.user_id IS NULL)")
            params.append(viewer_user_id)
            idx += 1
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    rs.*,
                    a.name                 AS account_name,
                    a.mask                 AS account_mask,
                    u.username             AS owner_username,
                    c.parent_id            AS category_parent_id,
                    COALESCE(pc.id, c.id)     AS primary_category_id,
                    COALESCE(pc.name, c.name) AS primary_category_name,
                    COALESCE(pc.color, c.color) AS primary_category_color
                FROM recurring_streams rs
                LEFT JOIN accounts a   ON a.id = rs.account_id
                LEFT JOIN users u      ON u.id = a.user_id
                LEFT JOIN categories c ON c.id = rs.category_id
                LEFT JOIN categories pc ON pc.id = c.parent_id
                {where}
                """,
                *params,
            )
        enriched: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            d.pop("category_parent_id", None)
            d["display_title"] = normalize_transaction_title(
                {
                    "merchant_name": d.get("merchant_name"),
                    "name": d.get("description"),
                    "description": d.get("description"),
                    "user_label": d.get("user_label"),
                }
            )
            if not (d.get("primary_category_name") or "").strip():
                fb = format_plaid_category_for_display(
                    d.get("pfc_detailed"),
                    d.get("pfc_primary"),
                )
                if fb:
                    d["primary_category_name"] = fb
            enriched.append(d)
        _sort_streams_by_next_payment(enriched)
        return enriched

    async def get_stream(self, stream_id: int) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM recurring_streams WHERE id = $1", stream_id)
        return dict(row) if row else None

    async def get_price_changes(
        self, viewer_user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Return streams where |last / avg - 1| > PRICE_CHANGE_THRESHOLD.

        `price_change_pct` is stored as a *signed* percentage where a positive
        value means the latest charge exceeds the long-term average. Callers
        (insights, UI) interpret the sign against `direction` to decide whether
        a change is favourable (e.g. price drop on an outflow subscription).
        Filtering still uses the absolute magnitude so drops and increases both
        surface as notable.

        When ``viewer_user_id`` is set, streams whose underlying account is
        owned by another user are hidden (see ``list_streams``).
        """
        pool = await self._pool()
        params: List[Any] = [PRICE_CHANGE_THRESHOLD]
        viewer_clause = ""
        if viewer_user_id is not None:
            viewer_clause = " AND (a.user_id = $2 OR a.user_id IS NULL)"
            params.append(viewer_user_id)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT rs.*
                FROM recurring_streams rs
                LEFT JOIN accounts a ON a.id = rs.account_id
                WHERE rs.is_active = TRUE
                  AND rs.last_amount_cents IS NOT NULL
                  AND rs.average_amount_cents IS NOT NULL
                  AND rs.average_amount_cents != 0
                  AND ABS(rs.last_amount_cents - rs.average_amount_cents)::float / ABS(rs.average_amount_cents) > $1
                  {viewer_clause}
                """,
                *params,
            )
        out = [dict(r) for r in rows]
        _sort_streams_by_next_payment(out)
        return out

    async def create_manual_stream(self, user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a user-defined recurring stream (same table as Plaid; never overwritten by sync)."""
        acct = await AccountsRepository().get_account(int(data["account_id"]))
        if not acct or acct.get("user_id") != user_id:
            raise ValueError("account_not_found_or_forbidden")
        last_cents = data.get("last_amount_cents")
        if last_cents is None:
            last_cents = int(data["average_amount_cents"])
        plaid_stream_id = f"manual:{uuid.uuid4()}"
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO recurring_streams (
                    plaid_stream_id, account_id, direction, description,
                    merchant_name, frequency, average_amount_cents, last_amount_cents,
                    currency, first_date, last_date, is_active, status,
                    category_id, stream_source, last_synced_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,TRUE,'MANUAL',$12,'manual',NOW()
                )
                RETURNING *
                """,
                plaid_stream_id,
                int(data["account_id"]),
                data["direction"],
                data["description"],
                data.get("merchant_name"),
                data.get("frequency"),
                int(data["average_amount_cents"]),
                int(last_cents),
                (data.get("currency") or "USD").strip() or "USD",
                data.get("first_date"),
                data.get("last_date"),
                data.get("category_id"),
            )
        return dict(row)

    async def update_stream(
        self, stream_id: int, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        allowed = {"user_label", "category_id"}
        fields = {k: v for k, v in data.items() if k in allowed}
        if not fields:
            return await self.get_stream(stream_id)
        set_clause = ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(fields.keys()))
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE recurring_streams SET {set_clause} WHERE id = $1 RETURNING *",
                stream_id,
                *fields.values(),
            )
        return dict(row) if row else None

    async def upsert_streams(
        self,
        plaid_streams: List[Dict[str, Any]],
        direction: str,
        account_id_map: Dict[str, int],
    ) -> int:
        """
        Upsert recurring streams from Plaid API response.
        account_id_map: {plaid_account_id: internal accounts.id}
        Returns count of upserted rows.
        """
        upserted = 0
        pool = await self._pool()
        async with pool.acquire() as conn:
            for stream in plaid_streams:
                plaid_stream_id = stream.get("stream_id", "")
                if not plaid_stream_id:
                    continue

                plaid_account_id = stream.get("account_id", "")
                account_id = account_id_map.get(plaid_account_id)

                avg_amount = stream.get("average_amount") or {}
                last_amount = stream.get("last_amount") or {}
                avg_cents = (
                    int(round(avg_amount["amount"] * 100))
                    if avg_amount.get("amount") is not None
                    else None
                )
                last_cents = (
                    int(round(last_amount["amount"] * 100))
                    if last_amount.get("amount") is not None
                    else None
                )

                # Calculate SIGNED price change pct. Positive = last charge
                # exceeds the long-term average; negative = latest is lower.
                # Using `abs(avg_cents)` as the denominator keeps the sign from
                # flipping for inflow streams where amounts are already
                # negative in Plaid's contract.
                price_change_pct = None
                if avg_cents and last_cents and avg_cents != 0:
                    pct = (last_cents - avg_cents) / abs(avg_cents)
                    price_change_pct = round(pct * 100, 2)

                pfc = stream.get("personal_finance_category") or {}
                pfc_primary = pfc.get("primary")
                pfc_detailed = pfc.get("detailed")

                currency = (
                    avg_amount.get("iso_currency_code")
                    or last_amount.get("iso_currency_code")
                    or "USD"
                )

                await conn.execute(
                    """
                    INSERT INTO recurring_streams (
                        plaid_stream_id, account_id, direction, description,
                        merchant_name, frequency, average_amount_cents, last_amount_cents,
                        currency, pfc_primary, pfc_detailed,
                        first_date, last_date, is_active, status,
                        price_change_pct, last_synced_at, stream_source
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,NOW(),'plaid')
                    ON CONFLICT (plaid_stream_id) DO UPDATE SET
                        account_id           = EXCLUDED.account_id,
                        direction            = EXCLUDED.direction,
                        description          = EXCLUDED.description,
                        merchant_name        = EXCLUDED.merchant_name,
                        frequency            = EXCLUDED.frequency,
                        average_amount_cents = EXCLUDED.average_amount_cents,
                        last_amount_cents    = EXCLUDED.last_amount_cents,
                        currency             = EXCLUDED.currency,
                        pfc_primary          = EXCLUDED.pfc_primary,
                        pfc_detailed         = EXCLUDED.pfc_detailed,
                        first_date           = EXCLUDED.first_date,
                        last_date            = EXCLUDED.last_date,
                        is_active            = EXCLUDED.is_active,
                        status               = EXCLUDED.status,
                        price_change_pct     = EXCLUDED.price_change_pct,
                        last_synced_at       = NOW()
                    WHERE recurring_streams.stream_source IS DISTINCT FROM 'manual'
                    """,
                    plaid_stream_id,
                    account_id,
                    direction,
                    stream.get("description", ""),
                    stream.get("merchant_name"),
                    stream.get("frequency"),
                    avg_cents,
                    last_cents,
                    currency,
                    pfc_primary,
                    pfc_detailed,
                    stream.get("first_date"),
                    stream.get("last_date"),
                    stream.get("is_active", True),
                    stream.get("status"),
                    price_change_pct,
                )
                upserted += 1
        return upserted
