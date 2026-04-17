"""
CategoriesRepository — DB operations for the categories table.

Auto-mapping logic:
  When a transaction is imported from Plaid, resolve_category(pfc_detailed) is called.
  If a category row with plaid_pfc_detailed matching the value exists → return its id.
  Otherwise create a new category row (source=plaid_pfc) using the PFC values from Plaid.
"""
import logging
from typing import Any, Dict, List, Optional

from web.db import get_pool

logger = logging.getLogger(__name__)

# Human-readable labels for PFC primary enum values (used only when building display names).
PFC_PRIMARY_LABELS: Dict[str, str] = {
    "INCOME": "Income",
    "TRANSFER_IN": "Transfer In",
    "TRANSFER_OUT": "Transfer Out",
    "LOAN_PAYMENTS": "Loan Payments",
    "BANK_FEES": "Bank Fees",
    "ENTERTAINMENT": "Entertainment",
    "FOOD_AND_DRINK": "Food & Drink",
    "GENERAL_MERCHANDISE": "Shopping",
    "HOME_IMPROVEMENT": "Home Improvement",
    "MEDICAL": "Medical",
    "PERSONAL_CARE": "Personal Care",
    "GENERAL_SERVICES": "Services",
    "GOVERNMENT_AND_NON_PROFIT": "Government & Non-Profit",
    "TRANSPORTATION": "Transportation",
    "TRAVEL": "Travel",
    "RENT_AND_UTILITIES": "Rent & Utilities",
}


def _pretty_name(pfc_detailed: str, pfc_primary: Optional[str] = None) -> str:
    """Convert FOOD_AND_DRINK_RESTAURANTS → Food & Drink: Restaurants."""
    primary_label = PFC_PRIMARY_LABELS.get(pfc_primary or "", pfc_primary or "")
    # Strip primary prefix from detailed if present
    if pfc_primary and pfc_detailed.startswith(pfc_primary + "_"):
        suffix = pfc_detailed[len(pfc_primary) + 1:]
    else:
        suffix = pfc_detailed
    suffix = suffix.replace("_", " ").title()
    if primary_label and suffix and suffix.upper() != pfc_primary:
        return f"{primary_label}: {suffix}"
    return suffix or primary_label


class CategoriesRepository:
    async def _pool(self):
        return await get_pool()

    async def list_categories(self) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM categories ORDER BY name")
        return [dict(r) for r in rows]

    async def get_category(self, category_id: int) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM categories WHERE id = $1", category_id)
        return dict(row) if row else None

    async def create_category(self, data: Dict[str, Any]) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO categories (name, plaid_pfc_primary, plaid_pfc_detailed, color, icon, pfc_icon_url, source)
                VALUES ($1, NULL, NULL, $2, $3, NULL, 'custom')
                ON CONFLICT (name) DO UPDATE SET
                    color = EXCLUDED.color,
                    icon = EXCLUDED.icon
                RETURNING *
                """,
                data["name"],
                data.get("color", "#3b82f6"),
                data.get("icon"),
            )
        return dict(row)

    async def update_category(
        self, category_id: int, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        allowed = {"name", "color", "icon"}
        fields = {k: v for k, v in data.items() if k in allowed}
        if not fields:
            return await self.get_category(category_id)
        pool = await self._pool()
        async with pool.acquire() as conn:
            set_clause = ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(fields.keys()))
            row = await conn.fetchrow(
                f"UPDATE categories SET {set_clause} WHERE id = $1 RETURNING *",
                category_id,
                *fields.values(),
            )
        return dict(row) if row else None

    async def delete_category(self, category_id: int) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT source FROM categories WHERE id = $1", category_id
            )
            if not row or row["source"] != "custom":
                return False
            result = await conn.execute(
                "DELETE FROM categories WHERE id = $1 AND source = 'custom'", category_id
            )
        return result != "DELETE 0"

    async def resolve_category(
        self,
        pfc_detailed: Optional[str],
        pfc_primary: Optional[str] = None,
        pfc_icon_url: Optional[str] = None,
    ) -> Optional[int]:
        """
        Return category id for a given PFC detailed value.
        Auto-creates a new category row (source=plaid_pfc) if none exists yet.
        Returns None if both pfc_detailed and pfc_primary are None.
        """
        if not pfc_detailed and not pfc_primary:
            return None

        pool = await self._pool()
        async with pool.acquire() as conn:
            # 1. Try exact match on plaid_pfc_detailed
            if pfc_detailed:
                row = await conn.fetchrow(
                    "SELECT id FROM categories WHERE plaid_pfc_detailed = $1", pfc_detailed
                )
                if row:
                    return row["id"]

            # 2. Try match on primary if no detailed match
            if pfc_primary and not pfc_detailed:
                row = await conn.fetchrow(
                    "SELECT id FROM categories WHERE plaid_pfc_primary = $1 AND plaid_pfc_detailed IS NULL",
                    pfc_primary,
                )
                if row:
                    return row["id"]

            # 3. Auto-create from Plaid PFC (never overwrite a custom row on name conflict)
            name = _pretty_name(pfc_detailed or pfc_primary or "Other", pfc_primary)
            row = await conn.fetchrow(
                """
                INSERT INTO categories (name, plaid_pfc_primary, plaid_pfc_detailed, pfc_icon_url, source)
                VALUES ($1, $2, $3, $4, 'plaid_pfc')
                ON CONFLICT (name) DO UPDATE SET
                    plaid_pfc_primary = EXCLUDED.plaid_pfc_primary,
                    plaid_pfc_detailed = EXCLUDED.plaid_pfc_detailed,
                    pfc_icon_url = EXCLUDED.pfc_icon_url,
                    source = 'plaid_pfc'
                WHERE categories.source = 'plaid_pfc'
                RETURNING id
                """,
                name,
                pfc_primary,
                pfc_detailed,
                pfc_icon_url,
            )
            if row:
                return row["id"]
            if pfc_detailed:
                row = await conn.fetchrow(
                    "SELECT id FROM categories WHERE plaid_pfc_detailed = $1", pfc_detailed
                )
                if row:
                    return row["id"]
            if pfc_primary:
                row = await conn.fetchrow(
                    """
                    SELECT id FROM categories
                    WHERE plaid_pfc_primary = $1 AND plaid_pfc_detailed IS NULL AND source = 'plaid_pfc'
                    """,
                    pfc_primary,
                )
                if row:
                    return row["id"]
            return None
