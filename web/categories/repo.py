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
        allowed = {"name", "color", "icon", "is_income"}
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

    async def _ensure_primary_category_id(self, conn, pfc_primary: str) -> Optional[int]:
        """
        Upsert a primary-only category row for ``pfc_primary`` and return its id.
        Idempotent. Invariant: primary rows have ``plaid_pfc_detailed IS NULL``
        and ``parent_id IS NULL``.
        """
        if not pfc_primary:
            return None
        row = await conn.fetchrow(
            """
            SELECT id FROM categories
            WHERE plaid_pfc_primary = $1 AND plaid_pfc_detailed IS NULL
            ORDER BY CASE WHEN source = 'plaid_pfc' THEN 0 ELSE 1 END, id
            LIMIT 1
            """,
            pfc_primary,
        )
        if row:
            return row["id"]
        label = PFC_PRIMARY_LABELS.get(pfc_primary, _pretty_name(pfc_primary, pfc_primary))
        # Plaid's INCOME primary is the default "what counts as income" bucket;
        # auto-flag every new INCOME parent so the new Income reports pick it
        # up without manual setup. Users can still flip the flag off later.
        is_income = pfc_primary == "INCOME"
        inserted = await conn.fetchrow(
            """
            INSERT INTO categories (name, plaid_pfc_primary, plaid_pfc_detailed, source, is_income)
            VALUES ($1, $2, NULL, 'plaid_pfc', $3)
            ON CONFLICT (name) DO NOTHING
            RETURNING id
            """,
            label,
            pfc_primary,
            is_income,
        )
        if inserted:
            return inserted["id"]
        # Name collided with a pre-existing row (likely a custom row).
        fallback = await conn.fetchrow(
            "SELECT id FROM categories WHERE name = $1", label
        )
        return fallback["id"] if fallback else None

    async def resolve_category(
        self,
        pfc_detailed: Optional[str],
        pfc_primary: Optional[str] = None,
        pfc_icon_url: Optional[str] = None,
    ) -> Optional[int]:
        """
        Return category id for a given PFC detailed value.
        Auto-creates a new category row (source=plaid_pfc) if none exists yet and
        ensures the row is linked to its primary-parent via ``parent_id``.
        Returns None if both pfc_detailed and pfc_primary are None.
        """
        if not pfc_detailed and not pfc_primary:
            return None

        pool = await self._pool()
        async with pool.acquire() as conn:
            parent_id = (
                await self._ensure_primary_category_id(conn, pfc_primary)
                if pfc_primary
                else None
            )

            # 1. Primary-only request → return the parent row id.
            if pfc_primary and not pfc_detailed:
                return parent_id

            # 2. Try exact match on plaid_pfc_detailed
            if pfc_detailed:
                row = await conn.fetchrow(
                    "SELECT id, parent_id FROM categories WHERE plaid_pfc_detailed = $1",
                    pfc_detailed,
                )
                if row:
                    if parent_id and row["parent_id"] != parent_id:
                        await conn.execute(
                            "UPDATE categories SET parent_id = $2 WHERE id = $1",
                            row["id"],
                            parent_id,
                        )
                    return row["id"]

            # 3. Auto-create detailed row (source=plaid_pfc) and link to parent.
            name = _pretty_name(pfc_detailed or pfc_primary or "Other", pfc_primary)
            # Every PFC INCOME_* subcategory (wages, interest, tax refund, ...)
            # counts as income by default; mirror the parent-row behaviour so
            # the new Income report captures newly-synced income subcategories
            # automatically. The ON CONFLICT clause does NOT touch is_income
            # so an existing user-set value is preserved.
            is_income = pfc_primary == "INCOME"
            row = await conn.fetchrow(
                """
                INSERT INTO categories (name, plaid_pfc_primary, plaid_pfc_detailed, pfc_icon_url, source, parent_id, is_income)
                VALUES ($1, $2, $3, $4, 'plaid_pfc', $5, $6)
                ON CONFLICT (name) DO UPDATE SET
                    plaid_pfc_primary = EXCLUDED.plaid_pfc_primary,
                    plaid_pfc_detailed = EXCLUDED.plaid_pfc_detailed,
                    pfc_icon_url = EXCLUDED.pfc_icon_url,
                    source = 'plaid_pfc',
                    parent_id = COALESCE(categories.parent_id, EXCLUDED.parent_id)
                WHERE categories.source = 'plaid_pfc'
                RETURNING id
                """,
                name,
                pfc_primary,
                pfc_detailed,
                pfc_icon_url,
                parent_id,
                is_income,
            )
            if row:
                return row["id"]
            if pfc_detailed:
                row = await conn.fetchrow(
                    "SELECT id FROM categories WHERE plaid_pfc_detailed = $1", pfc_detailed
                )
                if row:
                    return row["id"]
            return parent_id
