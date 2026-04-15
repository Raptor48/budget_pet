"""
Plaid database repository (asyncpg).
"""
import os
import json
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
                    income_added        INT DEFAULT 0,
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
            # Migrations: extend expenses table with Plaid-enriched fields
            for col_sql in [
                "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS plaid_transaction_id TEXT UNIQUE",
                "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual'",
                "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS merchant_name TEXT",
                "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS plaid_category_raw TEXT",
                "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS plaid_pfc_category TEXT",
                "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS is_pending BOOLEAN DEFAULT FALSE",
                "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS plaid_account_id TEXT",
            ]:
                await conn.execute(col_sql)
            # Migration: extend finance_income with plaid_transaction_id
            await conn.execute(
                "ALTER TABLE finance_income ADD COLUMN IF NOT EXISTS plaid_transaction_id TEXT UNIQUE"
            )
            # Migration: widen person CHECK constraint to include 'Plaid'
            await conn.execute("""
                DO $$
                BEGIN
                    ALTER TABLE finance_income DROP CONSTRAINT IF EXISTS finance_income_person_check;
                EXCEPTION WHEN OTHERS THEN NULL;
                END $$;
            """)
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'finance_income_person_check_v2'
                    ) THEN
                        ALTER TABLE finance_income ADD CONSTRAINT finance_income_person_check_v2
                            CHECK (person IN ('Denis', 'Taya', 'Plaid'));
                    END IF;
                END $$;
            """)
            # Migration: add income_added column to plaid_sync_log if missing
            await conn.execute(
                "ALTER TABLE plaid_sync_log ADD COLUMN IF NOT EXISTS income_added INT DEFAULT 0"
            )
            # Migration: add Plaid linking columns to finance tables
            for sql in [
                "ALTER TABLE finance_credit_cards ADD COLUMN IF NOT EXISTS plaid_account_id TEXT",
                "ALTER TABLE finance_loans ADD COLUMN IF NOT EXISTS plaid_account_id TEXT",
                "ALTER TABLE finance_credit_cards ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ",
                "ALTER TABLE finance_loans ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ",
            ]:
                await conn.execute(sql)
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

    async def reset_cursor(self, item_id: str) -> bool:
        """Set cursor to NULL so the next sync re-fetches all transactions from scratch."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE plaid_items SET cursor = NULL WHERE item_id = $1", item_id
            )
        return result == "UPDATE 1"

    # ------------------------------------------------------------------
    # Sync log
    # ------------------------------------------------------------------

    async def log_sync(self, item_id: str, transactions_added: int,
                       balances_updated: int, status: str,
                       error_msg: Optional[str] = None,
                       income_added: int = 0) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO plaid_sync_log
                    (item_id, transactions_added, income_added, balances_updated, status, error_msg)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, item_id, transactions_added, income_added, balances_updated, status, error_msg)

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

    def map_plaid_category(
        self,
        plaid_categories: list,
        category_map: Dict[str, str],
        pfc_category: Optional[str] = None,
    ) -> str:
        """Map Plaid transaction categories to budget category name.

        Priority:
        1. Legacy category array (most-specific first)
        2. personal_finance_category.detailed (PFC) — used when legacy is empty
        3. DEFAULT_BUDGET_CATEGORY
        """
        for cat in plaid_categories:
            if cat and cat in category_map:
                return category_map[cat]
        if pfc_category and pfc_category in category_map:
            return category_map[pfc_category]
        return DEFAULT_BUDGET_CATEGORY

    # ------------------------------------------------------------------
    # Transaction import into expenses table
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_txn_fields(txn) -> dict:
        """Extract all relevant fields from a Plaid transaction object."""
        # Convert SDK object to plain dict for reliable field access.
        # Plaid v9+ models have .to_dict(); fall back to dict-like .get().
        if hasattr(txn, "to_dict"):
            raw: dict = txn.to_dict()
        else:
            raw = txn  # already a dict

        merchant_name = raw.get("merchant_name") or raw.get("name") or ""
        plaid_cats = raw.get("category") or []
        plaid_category_raw = json.dumps(plaid_cats) if plaid_cats else None

        # personal_finance_category: SDK returns nested object or dict
        pfc = raw.get("personal_finance_category")
        plaid_pfc_category = None
        if pfc is not None:
            if isinstance(pfc, dict):
                plaid_pfc_category = pfc.get("detailed")
            elif hasattr(pfc, "to_dict"):
                plaid_pfc_category = pfc.to_dict().get("detailed")
            else:
                # Direct attribute access as last resort
                plaid_pfc_category = getattr(pfc, "detailed", None)

        is_pending = bool(raw.get("pending", False))
        account_id = raw.get("account_id")

        txn_date = raw.get("date")
        if isinstance(txn_date, str):
            txn_date = date.fromisoformat(txn_date)

        pfc_primary = None
        if pfc is not None:
            if isinstance(pfc, dict):
                pfc_primary = pfc.get("primary")
            elif hasattr(pfc, "to_dict"):
                pfc_primary = pfc.to_dict().get("primary")
            else:
                pfc_primary = getattr(pfc, "primary", None)

        return {
            "transaction_id": raw.get("transaction_id", ""),
            "amount": raw.get("amount", 0),
            "date": txn_date,
            "merchant_name": merchant_name,
            "plaid_cats": plaid_cats,
            "plaid_category_raw": plaid_category_raw,
            "plaid_pfc_category": plaid_pfc_category,
            "plaid_pfc_primary": pfc_primary,
            "is_pending": is_pending,
            "account_id": account_id,
        }

    async def _discover_categories(self, transactions: list) -> None:
        """
        Collect unique Plaid category strings from transactions and insert them
        into plaid_category_map with budget_category='Uncategorized' if not already present.
        This ensures categories appear in the UI after the first sync.
        """
        seen: set[str] = set()
        for txn in transactions:
            raw = txn.to_dict() if hasattr(txn, "to_dict") else txn
            cats = raw.get("category") or []
            for cat in cats:
                if cat:
                    seen.add(cat)
            # Also discover from personal_finance_category (PFC)
            pfc = raw.get("personal_finance_category")
            if pfc:
                pfc_dict = pfc if isinstance(pfc, dict) else (pfc.to_dict() if hasattr(pfc, "to_dict") else {})
                for key in ("primary", "detailed"):
                    val = pfc_dict.get(key)
                    if val:
                        seen.add(val)
        if not seen:
            return
        async with self._pool.acquire() as conn:
            await conn.executemany("""
                INSERT INTO plaid_category_map (plaid_category, budget_category)
                VALUES ($1, $2)
                ON CONFLICT (plaid_category) DO NOTHING
            """, [(cat, DEFAULT_BUDGET_CATEGORY) for cat in seen])

    async def import_transactions(self, transactions: list, category_map: Dict[str, str]) -> int:
        """
        Import Plaid debit transactions into the expenses table.
        Enriches rows with merchant_name, plaid_category_raw, plaid_pfc_category,
        is_pending, plaid_account_id. Skips duplicates by plaid_transaction_id.
        Marks source='plaid_sandbox' when PLAID_ENV=sandbox, otherwise 'plaid'.
        Returns count of newly added rows.
        """
        if not transactions:
            return 0

        # Auto-populate category map with any new Plaid categories seen in this batch
        await self._discover_categories(transactions)

        plaid_env = os.getenv("PLAID_ENV", "sandbox").lower()
        source = "plaid_sandbox" if plaid_env == "sandbox" else "plaid"

        added = 0
        async with self._pool.acquire() as conn:
            for txn in transactions:
                fields = self._extract_txn_fields(txn)
                amount = fields["amount"]

                # Only import debits (positive amount in Plaid = money leaving account)
                if amount <= 0:
                    continue

                budget_category = self.map_plaid_category(
                    fields["plaid_cats"], category_map, pfc_category=fields["plaid_pfc_category"]
                )

                try:
                    await conn.execute("""
                        INSERT INTO expenses (
                            category, amount, date, plaid_transaction_id, source,
                            merchant_name, plaid_category_raw, plaid_pfc_category,
                            is_pending, plaid_account_id
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        ON CONFLICT (plaid_transaction_id) DO UPDATE SET
                            is_pending = EXCLUDED.is_pending,
                            merchant_name = EXCLUDED.merchant_name,
                            plaid_category_raw = EXCLUDED.plaid_category_raw,
                            plaid_pfc_category = EXCLUDED.plaid_pfc_category
                    """,
                        budget_category, float(amount), str(fields["date"]),
                        fields["transaction_id"], source,
                        fields["merchant_name"], fields["plaid_category_raw"],
                        fields["plaid_pfc_category"], fields["is_pending"],
                        fields["account_id"]
                    )
                    added += 1
                except Exception as e:
                    logger.warning("Failed to import transaction %s: %s", fields["transaction_id"], e)

        return added

    async def remove_transactions(self, removed: list) -> int:
        """
        Delete Plaid-removed transactions from expenses and finance_income.
        Plaid 'removed' items contain only transaction_id.
        Returns total count of deleted rows across both tables.
        """
        if not removed:
            return 0

        ids = [txn.get("transaction_id", "") for txn in removed if txn.get("transaction_id")]
        if not ids:
            return 0

        deleted = 0
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM expenses WHERE plaid_transaction_id = ANY($1::text[])", ids
            )
            deleted += int(result.split()[-1])

            result = await conn.execute(
                "DELETE FROM finance_income WHERE plaid_transaction_id = ANY($1::text[])", ids
            )
            deleted += int(result.split()[-1])

        if deleted:
            logger.info("Removed %d Plaid-deleted transaction(s) from DB", deleted)
        return deleted

    async def import_income(self, transactions: list) -> int:
        """
        Import Plaid credit transactions (amount < 0) into finance_income as person='Plaid'.
        Skips refunds/returns by checking personal_finance_category when available.
        Skips duplicates by plaid_transaction_id.
        Returns count of newly added income rows.
        """
        if not transactions:
            return 0

        # Categories that are NOT income (refunds, cashback, adjustments)
        non_income_pfc = {
            "GENERAL_MERCHANDISE", "FOOD_AND_DRINK", "TRAVEL", "ENTERTAINMENT",
            "PERSONAL_CARE", "GENERAL_SERVICES", "HOME_IMPROVEMENT",
            "MEDICAL", "RENT_AND_UTILITIES", "LOAN_PAYMENTS",
        }

        added = 0
        async with self._pool.acquire() as conn:
            for txn in transactions:
                fields = self._extract_txn_fields(txn)
                amount = fields["amount"]

                # Only credits (negative amount = money coming in)
                if amount >= 0:
                    continue

                # Filter out non-income by personal_finance_category primary
                pfc_primary = fields["plaid_pfc_primary"]
                if pfc_primary and pfc_primary in non_income_pfc:
                    continue

                amount_cents = int(round(abs(amount) * 100))
                txn_date = fields["date"] or date.today()
                note = fields["merchant_name"] or fields["transaction_id"]

                try:
                    await conn.execute("""
                        INSERT INTO finance_income
                            (person, amount_cents, occurred_at, note, plaid_transaction_id)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (plaid_transaction_id) DO UPDATE SET
                            amount_cents = EXCLUDED.amount_cents,
                            note = EXCLUDED.note
                    """, "Plaid", amount_cents, str(txn_date), note, fields["transaction_id"])
                    added += 1
                except Exception as e:
                    logger.warning("Failed to import income %s: %s", fields["transaction_id"], e)

        return added

    # ------------------------------------------------------------------
    # Balance sync into finance tables
    # ------------------------------------------------------------------

    async def provision_finance_accounts(self, accounts: list) -> int:
        """
        Auto-create finance_credit_cards / finance_loans entries for Plaid accounts
        that don't yet exist. Uses plaid_account_id as the primary key and falls back
        to name matching to avoid creating duplicates for manually-entered records.
        Returns count of newly created entries.
        """
        created = 0
        async with self._pool.acquire() as conn:
            for acct in accounts:
                account_id = acct.get("account_id", "")
                name = acct.get("name") or acct.get("official_name") or ""
                acct_type = acct.get("type", "")
                subtype = acct.get("subtype", "")

                if not account_id or not name:
                    continue

                if acct_type == "credit":
                    # Check if already exists by plaid_account_id or name
                    exists = await conn.fetchval("""
                        SELECT 1 FROM finance_credit_cards
                        WHERE plaid_account_id = $1 OR LOWER(name) = LOWER($2)
                        LIMIT 1
                    """, account_id, name)
                    if not exists:
                        await conn.execute("""
                            INSERT INTO finance_credit_cards
                                (name, category_name, plaid_account_id, is_active)
                            VALUES ($1, $2, $3, TRUE)
                        """, name, "Credit Card", account_id)
                        created += 1
                        logger.info("Auto-provisioned credit card from Plaid: %s", name)
                    else:
                        # Ensure plaid_account_id is set if record was created manually
                        await conn.execute("""
                            UPDATE finance_credit_cards
                            SET plaid_account_id = $1
                            WHERE LOWER(name) = LOWER($2) AND plaid_account_id IS NULL
                        """, account_id, name)

                elif acct_type == "loan" or subtype in ("student", "mortgage", "auto", "consumer"):
                    exists = await conn.fetchval("""
                        SELECT 1 FROM finance_loans
                        WHERE plaid_account_id = $1 OR LOWER(name) = LOWER($2)
                        LIMIT 1
                    """, account_id, name)
                    if not exists:
                        category = "Student Loan" if subtype == "student" else "Loan"
                        await conn.execute("""
                            INSERT INTO finance_loans
                                (name, category_name, plaid_account_id, is_active)
                            VALUES ($1, $2, $3, TRUE)
                        """, name, category, account_id)
                        created += 1
                        logger.info("Auto-provisioned loan from Plaid: %s", name)
                    else:
                        await conn.execute("""
                            UPDATE finance_loans
                            SET plaid_account_id = $1
                            WHERE LOWER(name) = LOWER($2) AND plaid_account_id IS NULL
                        """, account_id, name)

        return created

    async def sync_balances(self, accounts: list) -> int:
        """
        Update current_balance_cents in finance_credit_cards and finance_loans.
        Matches by plaid_account_id first (fast path), then falls back to name.
        Returns count of updated records.
        """
        updated = 0
        async with self._pool.acquire() as conn:
            for acct in accounts:
                account_id = acct.get("account_id", "")
                name = acct.get("name", "")
                balances = acct.get("balances", {})
                current = balances.get("current")
                if current is None:
                    continue
                balance_cents = int(round(current * 100))
                acct_type = acct.get("type", "")

                if acct_type == "credit":
                    result = await conn.execute("""
                        UPDATE finance_credit_cards
                        SET current_balance_cents = $1, updated_at = now()
                        WHERE plaid_account_id = $2 AND is_active = TRUE
                    """, balance_cents, account_id)
                    if result == "UPDATE 0":
                        result = await conn.execute("""
                            UPDATE finance_credit_cards
                            SET current_balance_cents = $1, updated_at = now()
                            WHERE LOWER(name) = LOWER($2) AND is_active = TRUE
                        """, balance_cents, name)
                    if result != "UPDATE 0":
                        updated += 1

                elif acct_type == "loan":
                    result = await conn.execute("""
                        UPDATE finance_loans
                        SET current_balance_cents = $1, updated_at = now()
                        WHERE plaid_account_id = $2 AND is_active = TRUE
                    """, balance_cents, account_id)
                    if result == "UPDATE 0":
                        result = await conn.execute("""
                            UPDATE finance_loans
                            SET current_balance_cents = $1, updated_at = now()
                            WHERE LOWER(name) = LOWER($2) AND is_active = TRUE
                        """, balance_cents, name)
                    if result != "UPDATE 0":
                        updated += 1

        return updated

    async def sync_liabilities(self, liabilities: dict) -> int:
        """
        Update credit card details (APR, min_payment, due_date) and loan details
        from Plaid Liabilities API data.

        Matching strategy (for each liability):
        1. Match by plaid_account_id if already stored.
        2. Fall back to case-insensitive name match using account name from Plaid.
           On a name-based match, plaid_account_id is stored so future syncs use ID.

        Returns count of updated records.
        """
        updated = 0
        # Build map: plaid_account_id -> account_name from the accounts list
        account_name_map: Dict[str, str] = {
            a.get("account_id", ""): (a.get("name") or "")
            for a in liabilities.get("accounts", [])
        }

        async with self._pool.acquire() as conn:
            # --- Credit card liabilities ---
            for card_liability in liabilities.get("credit", []):
                account_id = card_liability.get("account_id", "")
                aprs = card_liability.get("aprs") or []
                min_payment = card_liability.get("minimum_payment_amount")
                next_due_date = card_liability.get("next_payment_due_date")
                last_stmt_balance = card_liability.get("last_statement_balance")

                # Prefer purchase APR; fall back to first available
                apr = None
                for apr_entry in aprs:
                    apr_type = apr_entry.get("apr_type", "")
                    if "purchase" in apr_type.lower() or apr is None:
                        apr = apr_entry.get("apr_percentage")

                min_payment_cents = int(round(min_payment * 100)) if min_payment is not None else None
                last_stmt_cents = int(round(last_stmt_balance * 100)) if last_stmt_balance is not None else None

                set_parts = ["last_synced_at = now()", "plaid_account_id = $1"]
                params: list = [account_id]
                idx = 2

                if apr is not None:
                    set_parts.append(f"apr_percent = ${idx}")
                    params.append(float(apr))
                    idx += 1
                if min_payment_cents is not None:
                    set_parts.append(f"min_payment_cents = ${idx}")
                    params.append(min_payment_cents)
                    idx += 1
                if last_stmt_cents is not None:
                    set_parts.append(f"current_balance_cents = ${idx}")
                    params.append(last_stmt_cents)
                    idx += 1
                if next_due_date:
                    set_parts.append(f"due_day = ${idx}")
                    try:
                        params.append(date.fromisoformat(str(next_due_date)).day)
                    except Exception:
                        params.append(None)
                    idx += 1

                # Attempt 1: match by stored plaid_account_id
                result = await conn.execute(
                    f"UPDATE finance_credit_cards SET {', '.join(set_parts)}"
                    " WHERE plaid_account_id = $1 AND is_active = TRUE",
                    *params,
                )
                if result != "UPDATE 0":
                    updated += 1
                    continue

                # Attempt 2: match by name and store plaid_account_id for future syncs
                acct_name = account_name_map.get(account_id, "")
                if acct_name:
                    result = await conn.execute(
                        f"UPDATE finance_credit_cards SET {', '.join(set_parts)}"
                        f" WHERE LOWER(name) = LOWER(${idx}) AND is_active = TRUE",
                        *params, acct_name,
                    )
                    if result != "UPDATE 0":
                        updated += 1

            # --- Loan / student loan liabilities ---
            for loan in liabilities.get("student", []):
                account_id = loan.get("account_id", "")
                interest_rate = loan.get("interest_rate_percentage")
                min_payment = loan.get("minimum_payment_amount")

                set_parts = ["last_synced_at = now()", "plaid_account_id = $1"]
                params = [account_id]
                idx = 2

                if interest_rate is not None:
                    set_parts.append(f"apr_percent = ${idx}")
                    params.append(float(interest_rate))
                    idx += 1
                if min_payment is not None:
                    set_parts.append(f"min_payment_cents = ${idx}")
                    params.append(int(round(min_payment * 100)))
                    idx += 1

                # Attempt 1: match by stored plaid_account_id
                result = await conn.execute(
                    f"UPDATE finance_loans SET {', '.join(set_parts)}"
                    " WHERE plaid_account_id = $1 AND is_active = TRUE",
                    *params,
                )
                if result != "UPDATE 0":
                    updated += 1
                    continue

                # Attempt 2: match by name
                acct_name = account_name_map.get(account_id, "")
                if acct_name:
                    result = await conn.execute(
                        f"UPDATE finance_loans SET {', '.join(set_parts)}"
                        f" WHERE LOWER(name) = LOWER(${idx}) AND is_active = TRUE",
                        *params, acct_name,
                    )
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
