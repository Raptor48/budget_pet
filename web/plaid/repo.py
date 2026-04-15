"""
Plaid database repository (asyncpg).
"""
import os
import logging
from datetime import date, datetime
from typing import Optional, List, Dict, Any

import asyncpg
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Default category for transactions without a mapping
DEFAULT_BUDGET_CATEGORY = "Uncategorized"


def _get_fernet() -> Fernet:
    """Return Fernet cipher using PLAID_ENCRYPTION_KEY env variable."""
    key = os.getenv("PLAID_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("PLAID_ENCRYPTION_KEY not set")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(token: str) -> str:
    return _get_fernet().encrypt(token.encode()).decode()


def decrypt_token(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()


class PlaidRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    # ------------------------------------------------------------------
    # Table initialisation
    # ------------------------------------------------------------------

    async def init_tables(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plaid_items (
                    id               SERIAL PRIMARY KEY,
                    item_id          TEXT UNIQUE NOT NULL,
                    access_token     TEXT NOT NULL,
                    institution_name TEXT,
                    connected_at     TIMESTAMPTZ DEFAULT now(),
                    last_synced_at   TIMESTAMPTZ,
                    cursor           TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plaid_sync_log (
                    id                  SERIAL PRIMARY KEY,
                    item_id             TEXT REFERENCES plaid_items(item_id) ON DELETE CASCADE,
                    synced_at           TIMESTAMPTZ DEFAULT now(),
                    transactions_added  INT DEFAULT 0,
                    balances_updated    INT DEFAULT 0,
                    status              TEXT,
                    error_msg           TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plaid_category_map (
                    plaid_category  TEXT PRIMARY KEY,
                    budget_category TEXT NOT NULL
                )
            """)
        logger.info("Plaid tables initialised")

    # ------------------------------------------------------------------
    # Items (connected bank accounts)
    # ------------------------------------------------------------------

    async def save_item(self, item_id: str, access_token: str, institution_name: Optional[str]) -> dict:
        encrypted = encrypt_token(access_token)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO plaid_items (item_id, access_token, institution_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (item_id) DO UPDATE
                    SET access_token = EXCLUDED.access_token,
                        institution_name = EXCLUDED.institution_name
                RETURNING id, item_id, institution_name, connected_at, last_synced_at
            """, item_id, encrypted, institution_name)
        return dict(row)

    async def get_items(self) -> List[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, item_id, institution_name, connected_at, last_synced_at FROM plaid_items ORDER BY connected_at DESC"
            )
        return [dict(r) for r in rows]

    async def get_item_with_token(self, item_id: str) -> Optional[dict]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM plaid_items WHERE item_id = $1", item_id)
        if not row:
            return None
        result = dict(row)
        result["access_token"] = decrypt_token(result["access_token"])
        return result

    async def get_all_items_with_tokens(self) -> List[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM plaid_items")
        result = []
        for row in rows:
            item = dict(row)
            item["access_token"] = decrypt_token(item["access_token"])
            result.append(item)
        return result

    async def delete_item(self, item_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM plaid_items WHERE item_id = $1", item_id)
        return result == "DELETE 1"

    async def update_cursor(self, item_id: str, cursor: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE plaid_items SET cursor = $1, last_synced_at = now() WHERE item_id = $2",
                cursor, item_id
            )

    # ------------------------------------------------------------------
    # Sync log
    # ------------------------------------------------------------------

    async def log_sync(self, item_id: str, transactions_added: int,
                       balances_updated: int, status: str, error_msg: Optional[str] = None) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO plaid_sync_log (item_id, transactions_added, balances_updated, status, error_msg)
                VALUES ($1, $2, $3, $4, $5)
            """, item_id, transactions_added, balances_updated, status, error_msg)

    async def get_sync_log(self, limit: int = 50) -> List[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM plaid_sync_log ORDER BY synced_at DESC LIMIT $1", limit
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Category mapping
    # ------------------------------------------------------------------

    async def get_category_map(self) -> Dict[str, str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT plaid_category, budget_category FROM plaid_category_map")
        return {r["plaid_category"]: r["budget_category"] for r in rows}

    async def upsert_category_mappings(self, mappings: List[Dict[str, str]]) -> None:
        async with self._pool.acquire() as conn:
            await conn.executemany("""
                INSERT INTO plaid_category_map (plaid_category, budget_category)
                VALUES ($1, $2)
                ON CONFLICT (plaid_category) DO UPDATE SET budget_category = EXCLUDED.budget_category
            """, [(m["plaid_category"], m["budget_category"]) for m in mappings])

    def map_plaid_category(self, plaid_categories: list, category_map: Dict[str, str]) -> str:
        """Map Plaid transaction categories to budget category name."""
        if not plaid_categories:
            return DEFAULT_BUDGET_CATEGORY
        # Try most-specific first, then parent
        for cat in plaid_categories:
            if cat in category_map:
                return category_map[cat]
        return DEFAULT_BUDGET_CATEGORY

    # ------------------------------------------------------------------
    # Transaction import into expenses table
    # ------------------------------------------------------------------

    async def import_transactions(self, transactions: list, category_map: Dict[str, str]) -> int:
        """
        Import Plaid transactions into the legacy expenses table.
        Skips duplicates (by plaid_transaction_id).
        Marks rows with source='plaid_sandbox' when PLAID_ENV=sandbox,
        otherwise source='plaid'. Sandbox rows are excluded from finance stats.
        Returns count of newly added rows.
        """
        if not transactions:
            return 0

        plaid_env = os.getenv("PLAID_ENV", "sandbox").lower()
        source = "plaid_sandbox" if plaid_env == "sandbox" else "plaid"

        added = 0
        async with self._pool.acquire() as conn:
            await conn.execute("""
                ALTER TABLE expenses
                ADD COLUMN IF NOT EXISTS plaid_transaction_id TEXT UNIQUE
            """)
            await conn.execute("""
                ALTER TABLE expenses
                ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual'
            """)

            for txn in transactions:
                # Skip positive amounts (income/refunds) — only import debits
                amount = txn.get("amount", 0)
                if amount <= 0:
                    continue

                txn_id = txn.get("transaction_id", "")
                txn_date = txn.get("date")
                if isinstance(txn_date, str):
                    txn_date = date.fromisoformat(txn_date)

                plaid_cats = txn.get("category") or []
                budget_category = self.map_plaid_category(plaid_cats, category_map)

                try:
                    await conn.execute("""
                        INSERT INTO expenses (category, amount, date, plaid_transaction_id, source)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (plaid_transaction_id) DO NOTHING
                    """, budget_category, float(amount), str(txn_date), txn_id, source)
                    added += 1
                except Exception as e:
                    logger.warning("Failed to import transaction %s: %s", txn_id, e)

        return added

    # ------------------------------------------------------------------
    # Balance sync into finance tables
    # ------------------------------------------------------------------

    async def sync_balances(self, accounts: list) -> int:
        """
        Update current_balance_cents in finance_credit_cards and finance_loans
        based on Plaid account name matching.
        Returns count of updated records.
        """
        updated = 0
        async with self._pool.acquire() as conn:
            for acct in accounts:
                name = acct.get("name", "")
                balances = acct.get("balances", {})
                current = balances.get("current")
                if current is None:
                    continue
                balance_cents = int(round(current * 100))
                acct_type = acct.get("type", "")

                if acct_type in ("credit", "loan"):
                    # Try credit cards
                    result = await conn.execute("""
                        UPDATE finance_credit_cards
                        SET current_balance_cents = $1, updated_at = now()
                        WHERE LOWER(name) = LOWER($2) AND is_active = TRUE
                    """, balance_cents, name)
                    if result != "UPDATE 0":
                        updated += 1
                        continue

                    # Try loans
                    result = await conn.execute("""
                        UPDATE finance_loans
                        SET current_balance_cents = $1, updated_at = now()
                        WHERE LOWER(name) = LOWER($2) AND is_active = TRUE
                    """, balance_cents, name)
                    if result != "UPDATE 0":
                        updated += 1

        return updated


_repo: Optional[PlaidRepository] = None


def get_plaid_repo() -> PlaidRepository:
    global _repo
    if _repo is None:
        raise RuntimeError("PlaidRepository not initialised. Call init_plaid_repo() first.")
    return _repo


async def init_plaid_repo() -> PlaidRepository:
    global _repo
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    _repo = PlaidRepository(pool)
    await _repo.init_tables()
    return _repo
