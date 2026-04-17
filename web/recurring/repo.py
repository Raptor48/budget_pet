"""
RecurringRepository — DB operations for recurring_streams.
Handles upsert from Plaid /transactions/recurring/get response,
price change detection (threshold 10%), and user label updates.
"""
import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from web.accounts.repo import AccountsRepository
from web.db import get_pool

logger = logging.getLogger(__name__)

PRICE_CHANGE_THRESHOLD = 0.10  # 10%


class RecurringRepository:
    async def _pool(self):
        return await get_pool()

    async def list_streams(
        self, direction: Optional[str] = None, active_only: bool = True
    ) -> List[Dict[str, Any]]:
        pool = await self._pool()
        conditions = []
        params = []
        idx = 1
        if direction:
            conditions.append(f"direction = ${idx}")
            params.append(direction)
            idx += 1
        if active_only:
            conditions.append("is_active = TRUE")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM recurring_streams {where} ORDER BY last_amount_cents DESC NULLS LAST",
                *params,
            )
        return [dict(r) for r in rows]

    async def get_stream(self, stream_id: int) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM recurring_streams WHERE id = $1", stream_id)
        return dict(row) if row else None

    async def get_price_changes(self) -> List[Dict[str, Any]]:
        """Return streams where last amount differs from average by more than 10%."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM recurring_streams
                WHERE is_active = TRUE
                  AND last_amount_cents IS NOT NULL
                  AND average_amount_cents IS NOT NULL
                  AND average_amount_cents != 0
                  AND ABS(last_amount_cents - average_amount_cents)::float / ABS(average_amount_cents) > $1
                ORDER BY ABS(last_amount_cents - average_amount_cents) DESC
                """,
                PRICE_CHANGE_THRESHOLD,
            )
        return [dict(r) for r in rows]

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

                # Calculate price change pct
                price_change_pct = None
                if avg_cents and last_cents and avg_cents != 0:
                    pct = abs(last_cents - avg_cents) / abs(avg_cents)
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
