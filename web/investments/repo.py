"""
InvestmentsRepository — DB operations for securities and investment_holdings.
"""
import logging
from typing import Any, Dict, List, Optional

from web.db import get_pool

logger = logging.getLogger(__name__)


class InvestmentsRepository:
    async def _pool(self):
        return await get_pool()

    async def list_holdings(self, account_id: Optional[int] = None) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            if account_id:
                rows = await conn.fetch(
                    """
                    SELECT h.*, row_to_json(s.*) AS security
                    FROM investment_holdings h
                    LEFT JOIN securities s ON s.plaid_security_id = h.security_id
                    WHERE h.account_id = $1
                    ORDER BY h.institution_value_cents DESC NULLS LAST
                    """,
                    account_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT h.*, row_to_json(s.*) AS security
                    FROM investment_holdings h
                    LEFT JOIN securities s ON s.plaid_security_id = h.security_id
                    ORDER BY h.institution_value_cents DESC NULLS LAST
                    """
                )
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("security"), str):
                import json
                d["security"] = json.loads(d["security"])
            result.append(d)
        return result

    async def upsert_securities(self, securities: List[Dict[str, Any]]) -> int:
        pool = await self._pool()
        upserted = 0
        async with pool.acquire() as conn:
            for sec in securities:
                plaid_id = sec.get("security_id", "")
                if not plaid_id:
                    continue
                close_price = sec.get("close_price")
                close_price_date = sec.get("close_price_as_of")
                await conn.execute(
                    """
                    INSERT INTO securities (
                        plaid_security_id, name, ticker_symbol, type, subtype,
                        close_price, close_price_as_of, sector, industry, currency
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (plaid_security_id) DO UPDATE SET
                        name              = EXCLUDED.name,
                        ticker_symbol     = EXCLUDED.ticker_symbol,
                        type              = EXCLUDED.type,
                        subtype           = EXCLUDED.subtype,
                        close_price       = EXCLUDED.close_price,
                        close_price_as_of = EXCLUDED.close_price_as_of,
                        sector            = EXCLUDED.sector,
                        industry          = EXCLUDED.industry,
                        updated_at        = NOW()
                    """,
                    plaid_id,
                    sec.get("name"),
                    sec.get("ticker_symbol"),
                    sec.get("type"),
                    sec.get("unofficial_currency_code") or sec.get("subtype"),
                    float(close_price) if close_price is not None else None,
                    close_price_date,
                    sec.get("sector"),
                    sec.get("industry"),
                    sec.get("iso_currency_code") or "USD",
                )
                upserted += 1
        return upserted

    async def upsert_holdings(
        self, holdings: List[Dict[str, Any]], account_id_map: Dict[str, int]
    ) -> int:
        pool = await self._pool()
        upserted = 0
        async with pool.acquire() as conn:
            for h in holdings:
                plaid_account_id = h.get("account_id", "")
                account_id = account_id_map.get(plaid_account_id)
                if not account_id:
                    logger.warning("No account found for plaid_account_id=%s", plaid_account_id)
                    continue
                security_id = h.get("security_id", "")
                if not security_id:
                    continue

                quantity = h.get("quantity")
                inst_price = h.get("institution_price")
                inst_value = h.get("institution_value")
                cost_basis = h.get("cost_basis")
                currency = h.get("iso_currency_code") or "USD"

                inst_value_cents = int(round(inst_value * 100)) if inst_value is not None else None
                cost_basis_cents = int(round(cost_basis * 100)) if cost_basis is not None else None

                await conn.execute(
                    """
                    INSERT INTO investment_holdings (
                        account_id, security_id, quantity,
                        institution_price, institution_value_cents, cost_basis_cents, currency
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (account_id, security_id) DO UPDATE SET
                        quantity                = EXCLUDED.quantity,
                        institution_price       = EXCLUDED.institution_price,
                        institution_value_cents = EXCLUDED.institution_value_cents,
                        cost_basis_cents        = EXCLUDED.cost_basis_cents,
                        currency                = EXCLUDED.currency,
                        last_synced_at          = NOW()
                    """,
                    account_id,
                    security_id,
                    float(quantity) if quantity is not None else 0,
                    float(inst_price) if inst_price is not None else None,
                    inst_value_cents,
                    cost_basis_cents,
                    currency,
                )
                upserted += 1
        return upserted
