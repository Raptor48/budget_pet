"""
PlaidRepository V2 — DB operations for Plaid sync using the new V2 schema.

Tables used:
  - plaid_items     (unchanged)
  - plaid_sync_log  (unchanged)
  - accounts        (V2: single unified accounts table)
  - transactions    (V2: single unified transactions table)
  - categories      (V2: auto-resolved via PFC)

This module replaces the V1 implementation that used expenses + finance_* tables.
"""
import json
import logging
from typing import Any, Dict, List, Optional

import asyncpg

from web.db import get_pool

logger = logging.getLogger(__name__)

_pool_instance: Optional[asyncpg.Pool] = None


def get_plaid_repo() -> "PlaidRepository":
    return PlaidRepository()


class PlaidRepository:
    async def _pool(self) -> asyncpg.Pool:
        return await get_pool()

    # ------------------------------------------------------------------
    # Items (plaid_items table — unchanged schema)
    # ------------------------------------------------------------------

    async def init_tables(self) -> None:
        """Ensure plaid_items and plaid_sync_log tables exist."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plaid_items (
                    item_id              TEXT PRIMARY KEY,
                    access_token         TEXT NOT NULL,
                    institution_name     TEXT,
                    institution_logo     TEXT,
                    institution_color    VARCHAR(7),
                    cursor               TEXT,
                    connected_at         TIMESTAMPTZ DEFAULT NOW(),
                    last_synced_at       TIMESTAMPTZ
                )
            """)
            # Additive columns for existing installations (idempotent)
            for col_sql in (
                "ALTER TABLE plaid_items ADD COLUMN IF NOT EXISTS institution_logo TEXT",
                "ALTER TABLE plaid_items ADD COLUMN IF NOT EXISTS institution_color VARCHAR(7)",
                "ALTER TABLE plaid_items ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
                "ALTER TABLE plaid_items ADD COLUMN IF NOT EXISTS item_login_required BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE plaid_items ADD COLUMN IF NOT EXISTS sync_updates_pending BOOLEAN NOT NULL DEFAULT FALSE",
            ):
                try:
                    await conn.execute(col_sql)
                except Exception:
                    pass
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plaid_sync_log (
                    id                   SERIAL PRIMARY KEY,
                    item_id              TEXT NOT NULL,
                    synced_at            TIMESTAMPTZ DEFAULT NOW(),
                    transactions_added   INT DEFAULT 0,
                    income_added         INT DEFAULT 0,
                    balances_updated     INT DEFAULT 0,
                    status               TEXT DEFAULT 'ok',
                    error_msg            TEXT
                )
            """)

    async def save_item(
        self,
        item_id: str,
        access_token: str,
        institution_name: Optional[str] = None,
        institution_logo: Optional[str] = None,
        institution_color: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO plaid_items
                    (item_id, access_token, institution_name, institution_logo, institution_color, user_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (item_id) DO UPDATE SET
                    access_token      = EXCLUDED.access_token,
                    institution_name  = COALESCE(EXCLUDED.institution_name,  plaid_items.institution_name),
                    institution_logo  = COALESCE(EXCLUDED.institution_logo,  plaid_items.institution_logo),
                    institution_color = COALESCE(EXCLUDED.institution_color, plaid_items.institution_color),
                    user_id           = COALESCE(plaid_items.user_id,        EXCLUDED.user_id)
                RETURNING *
                """,
                item_id, access_token, institution_name, institution_logo, institution_color, user_id,
            )
        return dict(row)

    async def get_items(self) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM plaid_items ORDER BY connected_at")
        return [dict(r) for r in rows]

    async def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM plaid_items WHERE item_id = $1", item_id)
        return dict(row) if row else None

    async def delete_item(self, item_id: str) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM plaid_items WHERE item_id = $1", item_id)
        return result != "DELETE 0"

    async def get_item_data_summary(self, item_id: str) -> Dict[str, int]:
        """
        Return counts of DB rows owned by a single Plaid item. Used by the UI to
        warn the user before destructive delete + purge operations.

        Only counts rows that ``purge_item`` would actually remove: accounts tied
        to the item, and Plaid-sourced transactions on those accounts. Cash /
        manual transactions are never counted because they are not removed.
        """
        pool = await self._pool()
        async with pool.acquire() as conn:
            accounts_count_row = await conn.fetchrow(
                "SELECT COUNT(*) AS c FROM accounts WHERE plaid_item_id = $1",
                item_id,
            )
            accounts_count = int(accounts_count_row["c"]) if accounts_count_row else 0

            txn_count_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS c
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                WHERE a.plaid_item_id = $1
                  AND t.source IN ('plaid', 'plaid_sandbox')
                """,
                item_id,
            )
            txn_count = int(txn_count_row["c"]) if txn_count_row else 0
        return {
            "accounts_count": accounts_count,
            "transactions_count": txn_count,
        }

    async def purge_item(self, item_id: str) -> Dict[str, int]:
        """
        Fully remove a Plaid item and all data it brought in.

        Deletion order respects FK constraints. Only Plaid-sourced transactions
        are deleted; cash/manual transactions on any unrelated account are never
        touched. Accounts without a ``plaid_item_id`` (cash wallets) are never
        touched either.

        Returns counts of deleted rows per table, mirroring ``delete_sandbox_data``.
        """
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                account_rows = await conn.fetch(
                    "SELECT id FROM accounts WHERE plaid_item_id = $1",
                    item_id,
                )
                account_ids = [r["id"] for r in account_rows]

                tx_count = 0
                stream_count = 0
                if account_ids:
                    tx_id_rows = await conn.fetch(
                        """
                        SELECT id FROM transactions
                        WHERE account_id = ANY($1::int[])
                          AND source IN ('plaid', 'plaid_sandbox')
                        """,
                        account_ids,
                    )
                    tx_ids = [r["id"] for r in tx_id_rows]
                    tx_count = len(tx_ids)
                    if tx_ids:
                        await conn.execute(
                            "DELETE FROM transaction_tags WHERE transaction_id = ANY($1::int[])",
                            tx_ids,
                        )
                        await conn.execute(
                            "DELETE FROM transaction_splits WHERE parent_transaction_id = ANY($1::int[])",
                            tx_ids,
                        )
                        await conn.execute(
                            "DELETE FROM transactions WHERE id = ANY($1::int[])",
                            tx_ids,
                        )

                    stream_result = await conn.execute(
                        "DELETE FROM recurring_streams WHERE account_id = ANY($1::int[])",
                        account_ids,
                    )
                    stream_count = int(stream_result.split()[-1]) if stream_result else 0

                    await conn.execute(
                        "DELETE FROM investment_holdings WHERE account_id = ANY($1::int[])",
                        account_ids,
                    )
                    await conn.execute(
                        """
                        DELETE FROM securities
                        WHERE plaid_security_id NOT IN (
                            SELECT DISTINCT security_id FROM investment_holdings
                        )
                        """
                    )

                await conn.execute(
                    "DELETE FROM plaid_sync_log WHERE item_id = $1",
                    item_id,
                )

                accounts_deleted = 0
                if account_ids:
                    acc_result = await conn.execute(
                        "DELETE FROM accounts WHERE id = ANY($1::int[])",
                        account_ids,
                    )
                    accounts_deleted = int(acc_result.split()[-1]) if acc_result else 0

                item_result = await conn.execute(
                    "DELETE FROM plaid_items WHERE item_id = $1",
                    item_id,
                )
                items_deleted = int(item_result.split()[-1]) if item_result else 0

        logger.info(
            "Purged Plaid item %s: %d transactions, %d accounts, %d recurring streams, item_deleted=%d",
            item_id,
            tx_count,
            accounts_deleted,
            stream_count,
            items_deleted,
        )
        return {
            "transactions_deleted": tx_count,
            "accounts_deleted": accounts_deleted,
            "recurring_streams_deleted": stream_count,
            "plaid_items_deleted": items_deleted,
        }

    async def update_cursor(self, item_id: str, cursor: str) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE plaid_items SET cursor = $2, last_synced_at = NOW() WHERE item_id = $1",
                item_id, cursor,
            )

    async def reset_cursor(self, item_id: str) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE plaid_items SET cursor = NULL, last_synced_at = NULL WHERE item_id = $1",
                item_id,
            )
        return result != "UPDATE 0"

    async def set_item_login_required(self, item_id: str, value: bool = True) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE plaid_items SET item_login_required = $2 WHERE item_id = $1",
                item_id,
                value,
            )

    async def set_sync_updates_pending(self, item_id: str, value: bool = True) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE plaid_items SET sync_updates_pending = $2 WHERE item_id = $1",
                item_id,
                value,
            )

    async def clear_connection_flags(self, item_id: str) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE plaid_items SET
                    item_login_required = FALSE,
                    sync_updates_pending = FALSE
                WHERE item_id = $1
                """,
                item_id,
            )

    async def try_insert_webhook_event(self, webhook_id: str) -> bool:
        """Return True if inserted (new), False if duplicate webhook_id."""
        if not webhook_id:
            return True
        pool = await self._pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO plaid_webhook_events (webhook_id) VALUES ($1)",
                    webhook_id,
                )
            return True
        except asyncpg.UniqueViolationError:
            return False

    # ------------------------------------------------------------------
    # Sync log
    # ------------------------------------------------------------------

    async def log_sync(
        self,
        item_id: str,
        transactions_added: int = 0,
        balances_updated: int = 0,
        status: str = "ok",
        error_msg: Optional[str] = None,
    ) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO plaid_sync_log
                    (item_id, transactions_added, income_added, balances_updated, status, error_msg)
                VALUES ($1,$2,0,$3,$4,$5)
                """,
                item_id, transactions_added, balances_updated, status, error_msg,
            )

    async def get_sync_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM plaid_sync_log ORDER BY synced_at DESC LIMIT $1", limit
            )
        return [dict(r) for r in rows]

    async def clear_sync_log(self) -> int:
        """Remove every row from ``plaid_sync_log``.

        Called from ``DELETE /api/plaid/sync/log`` after owner-only auth.
        Returns the number of rows deleted so callers can surface the count
        to the user.
        """
        pool = await self._pool()
        async with pool.acquire() as conn:
            status = await conn.execute("DELETE FROM plaid_sync_log")
        if not status:
            return 0
        tail = status.split()[-1]
        return int(tail) if tail.isdigit() else 0

    # ------------------------------------------------------------------
    # Transactions import (V2 — writes to transactions table)
    # ------------------------------------------------------------------

    def _extract_txn(self, raw: Dict[str, Any], account_id: int, source: str) -> Dict[str, Any]:
        """Convert a Plaid transaction dict to a transactions table row dict."""
        pfc = raw.get("personal_finance_category") or {}
        if hasattr(pfc, "to_dict"):
            pfc = pfc.to_dict()

        amount = raw.get("amount")
        # Plaid: amount > 0 = debit (expense); amount < 0 = credit (income)
        # Use explicit None check so that a legitimate 0.0 amount is preserved.
        amount_cents = int(round(amount * 100)) if amount is not None else 0

        location = raw.get("location")
        if hasattr(location, "to_dict"):
            location = location.to_dict()

        payment_meta = raw.get("payment_meta")
        if hasattr(payment_meta, "to_dict"):
            payment_meta = payment_meta.to_dict()

        counterparties = raw.get("counterparties") or []
        if isinstance(counterparties, list):
            counterparties = [
                c.to_dict() if hasattr(c, "to_dict") else c for c in counterparties
            ]

        currency = raw.get("iso_currency_code") or raw.get("unofficial_currency_code") or "USD"

        return {
            "plaid_transaction_id": raw.get("transaction_id"),
            "account_id": account_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "date": raw.get("date"),
            "authorized_date": raw.get("authorized_date"),
            "datetime": raw.get("datetime"),
            "authorized_datetime": raw.get("authorized_datetime"),
            "name": raw.get("name") or "",
            "merchant_name": raw.get("merchant_name"),
            "merchant_entity_id": raw.get("merchant_entity_id"),
            "logo_url": raw.get("logo_url"),
            "website": raw.get("website"),
            "payment_channel": raw.get("payment_channel"),
            "pfc_primary": pfc.get("primary"),
            "pfc_detailed": pfc.get("detailed"),
            # Plaid Transactions API: personal_finance_category.confidence_level (enum string)
            "pfc_confidence": pfc.get("confidence_level"),
            "pfc_icon_url": raw.get("personal_finance_category_icon_url"),
            "counterparties": counterparties if counterparties else None,
            "location": location,
            "payment_meta": payment_meta,
            "is_pending": raw.get("pending", False),
            # Set on a posted transaction that replaces a pending twin. We use
            # it to forward user-set fields (is_private, user_note) before the
            # pending row is removed by /transactions/sync.
            "pending_transaction_id": raw.get("pending_transaction_id"),
            "source": source,
        }

    async def import_transactions(
        self,
        plaid_transactions: List[Any],
        account_id_map: Dict[str, int],
        source: str,
        category_resolver=None,
        user_id: Optional[int] = None,
    ) -> int:
        """
        Upsert transactions from Plaid into the transactions table.
        Uses ON CONFLICT (plaid_transaction_id) to handle duplicates.
        Returns count of rows inserted/updated.
        """
        if not plaid_transactions:
            return 0

        pool = await self._pool()
        imported = 0

        async with pool.acquire() as conn:
            # Load the internal-transfer names list once per sync batch —
            # these are family-wide so every row we classify uses the same
            # snapshot. Cheap query; we don't reach into Python settings
            # because the list can be edited between syncs.
            from web.plaid.internal_transfer import (
                classify_internal_transfer,
                get_configured_names,
            )
            internal_names = await get_configured_names(conn)

            for txn in plaid_transactions:
                raw = txn.to_dict() if hasattr(txn, "to_dict") else txn
                plaid_account_id = raw.get("account_id", "")
                account_id = account_id_map.get(plaid_account_id)
                if not account_id:
                    logger.warning("No account for plaid_account_id=%s, skipping", plaid_account_id)
                    continue

                data = self._extract_txn(raw, account_id, source)

                # Resolve category from PFC, then optional user merchant rule (overrides PFC)
                category_id = None
                if category_resolver and (data.get("pfc_detailed") or data.get("pfc_primary")):
                    try:
                        category_id = await category_resolver(
                            data.get("pfc_detailed"),
                            data.get("pfc_primary"),
                            data.get("pfc_icon_url"),
                        )
                    except Exception as exc:
                        logger.warning("Category resolve failed: %s", exc)
                from web.merchant_rules.repo import MerchantRulesRepository
                from web.transactions.display import normalize_transaction_title

                data["display_title"] = normalize_transaction_title(data)

                rule_cat = await MerchantRulesRepository().lookup_category(
                    data.get("merchant_entity_id"),
                    data.get("merchant_name"),
                    data.get("display_title"),
                )
                if rule_cat is not None:
                    category_id = rule_cat
                data["category_id"] = category_id

                # When Plaid posts a previously-pending transaction, the new
                # row gets a fresh plaid_transaction_id and the old (pending)
                # row is reported in `removed`. Carry user-set flags from the
                # pending twin so privacy and notes survive the re-keying.
                # delete_removed_transactions runs *after* import in the
                # scheduler, so the pending row is still present here.
                carry_is_private = False
                carry_user_note = None
                carry_category_id = None
                pending_ref = data.get("pending_transaction_id")
                if pending_ref:
                    pending_row = await conn.fetchrow(
                        """
                        SELECT is_private, user_note, category_id
                        FROM transactions
                        WHERE plaid_transaction_id = $1
                        """,
                        pending_ref,
                    )
                    if pending_row is not None:
                        carry_is_private = bool(pending_row["is_private"])
                        carry_user_note = pending_row["user_note"]
                        carry_category_id = pending_row["category_id"]

                # A user-assigned category on the pending row always wins over
                # Plaid's default categorisation for the posted twin; the
                # merchant-rule lookup above still takes precedence because it
                # was applied first, but a user override from the pending row
                # trumps raw PFC.
                if carry_category_id is not None and rule_cat is None:
                    data["category_id"] = carry_category_id

                # Classify as internal transfer (Zelle between family members
                # etc.). Only set the flag on INSERT; existing rows keep
                # whatever the user explicitly chose. If the pending twin had
                # a user-flagged value, propagate it so the posted row
                # inherits the manual decision.
                auto_internal = classify_internal_transfer(
                    pfc_primary=data.get("pfc_primary"),
                    merchant_name=data.get("merchant_name"),
                    name=data.get("name"),
                    counterparties=data.get("counterparties"),
                    normalized_names=internal_names,
                )
                carry_internal = False
                carry_internal_manual = False
                if pending_ref:
                    pending_flags = await conn.fetchrow(
                        """
                        SELECT is_internal_transfer, is_internal_transfer_manual
                        FROM transactions
                        WHERE plaid_transaction_id = $1
                        """,
                        pending_ref,
                    )
                    if pending_flags is not None:
                        carry_internal = bool(pending_flags["is_internal_transfer"])
                        carry_internal_manual = bool(
                            pending_flags["is_internal_transfer_manual"]
                        )
                is_internal_value = carry_internal if carry_internal_manual else auto_internal

                await conn.execute(
                    """
                    INSERT INTO transactions (
                        plaid_transaction_id, account_id, category_id,
                        amount_cents, currency, date, authorized_date,
                        datetime, authorized_datetime, name, merchant_name,
                        merchant_entity_id, logo_url, website, payment_channel,
                        pfc_primary, pfc_detailed, pfc_confidence, pfc_icon_url,
                        counterparties, location, payment_meta,
                        is_pending, source, display_title,
                        pending_transaction_id, is_private, user_note,
                        is_internal_transfer, is_internal_transfer_manual
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                        $16,$17,$18,$19,$20,$21,$22,$23,$24,$25,
                        $26,$27,$28,$29,$30
                    )
                    ON CONFLICT (plaid_transaction_id) DO UPDATE SET
                        account_id          = EXCLUDED.account_id,
                        category_id         = COALESCE(transactions.category_id, EXCLUDED.category_id),
                        amount_cents        = EXCLUDED.amount_cents,
                        date                = EXCLUDED.date,
                        authorized_date     = EXCLUDED.authorized_date,
                        datetime            = EXCLUDED.datetime,
                        authorized_datetime = EXCLUDED.authorized_datetime,
                        name                = EXCLUDED.name,
                        merchant_name       = EXCLUDED.merchant_name,
                        merchant_entity_id  = EXCLUDED.merchant_entity_id,
                        logo_url            = EXCLUDED.logo_url,
                        website             = EXCLUDED.website,
                        payment_channel     = EXCLUDED.payment_channel,
                        pfc_primary         = EXCLUDED.pfc_primary,
                        pfc_detailed        = EXCLUDED.pfc_detailed,
                        pfc_confidence      = EXCLUDED.pfc_confidence,
                        pfc_icon_url        = EXCLUDED.pfc_icon_url,
                        counterparties      = EXCLUDED.counterparties,
                        location            = EXCLUDED.location,
                        payment_meta        = EXCLUDED.payment_meta,
                        is_pending          = EXCLUDED.is_pending,
                        source              = EXCLUDED.source,
                        display_title       = EXCLUDED.display_title,
                        pending_transaction_id = EXCLUDED.pending_transaction_id,
                        -- Preserve the internal-transfer flag on updates so
                        -- a manual user toggle (or the first-time auto
                        -- classification from INSERT) survives subsequent
                        -- Plaid /transactions/sync calls that refresh the
                        -- row's other fields.
                        updated_at          = NOW()
                    """,
                    data.get("plaid_transaction_id"),
                    data["account_id"],
                    data.get("category_id"),
                    data["amount_cents"],
                    data.get("currency", "USD"),
                    data.get("date"),
                    data.get("authorized_date"),
                    data.get("datetime"),
                    data.get("authorized_datetime"),
                    data["name"],
                    data.get("merchant_name"),
                    data.get("merchant_entity_id"),
                    data.get("logo_url"),
                    data.get("website"),
                    data.get("payment_channel"),
                    data.get("pfc_primary"),
                    data.get("pfc_detailed"),
                    data.get("pfc_confidence"),
                    data.get("pfc_icon_url"),
                    json.dumps(data["counterparties"]) if data.get("counterparties") else None,
                    json.dumps(data["location"]) if data.get("location") else None,
                    json.dumps(data["payment_meta"]) if data.get("payment_meta") else None,
                    data.get("is_pending", False),
                    data.get("source", "plaid"),
                    data.get("display_title"),
                    pending_ref,
                    carry_is_private,
                    carry_user_note,
                    is_internal_value,
                    carry_internal_manual,
                )
                imported += 1

            # Run the unified classifier over the last 7 days so freshly
            # synced rows get the correct ``transaction_class`` immediately
            # — no manual rescan needed. This covers both the classic
            # TRANSFER_OUT/IN pair (savings ↔ checking, same amount across
            # spouses) and the cash ↔ debt case (checking pays off a
            # credit card; the depository side tagged LOAN_PAYMENTS never
            # made it into the old pair matcher). 7 days is long enough for
            # ACH settlement + weekends; the full-history rescan remains an
            # explicit endpoint for cleanup passes.
            try:
                from web.classification.classifier import rescan_all

                stats = await rescan_all(conn, horizon_days=7)
                if stats.changed:
                    logger.info(
                        "Plaid import: reclassified %d rows (paired=%d)",
                        stats.changed,
                        stats.paired,
                    )
            except Exception:
                logger.exception(
                    "Plaid import: classification rescan failed; continuing"
                )

        return imported

    async def delete_removed_transactions(self, removed: List[Any]) -> int:
        """Delete transactions that Plaid reports as removed."""
        if not removed:
            return 0
        plaid_ids = []
        for txn in removed:
            raw = txn.to_dict() if hasattr(txn, "to_dict") else txn
            tid = raw.get("transaction_id") or raw.get("plaid_transaction_id")
            if tid:
                plaid_ids.append(tid)
        if not plaid_ids:
            return 0
        pool = await self._pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM transactions WHERE plaid_transaction_id = ANY($1::text[])",
                plaid_ids,
            )
        count_str = result.split()[-1] if result else "0"
        return int(count_str) if count_str.isdigit() else 0

    # ------------------------------------------------------------------
    # Accounts  (liabilities update — syncs APR, min_payment, etc.)
    # ------------------------------------------------------------------

    async def sync_liabilities_to_accounts(self, liabilities: Dict[str, Any]) -> int:
        """
        Update accounts table with APR, min_payment, due date, overdue flags
        from Plaid liabilities response.
        Matches by plaid_account_id on the accounts table.
        Returns count of updated rows.
        """
        updated = 0
        pool = await self._pool()

        async with pool.acquire() as conn:
            # --- Credit cards ---
            # Plaid apr_type enum values: purchase_apr, cash_apr, balance_transfer_apr, special
            _PURCHASE_APR_TYPES = ("purchase_apr", "cash_apr", "balance_transfer_apr", "special")

            for card in liabilities.get("credit") or []:
                card = card.to_dict() if hasattr(card, "to_dict") else card
                plaid_account_id = card.get("account_id", "")
                aprs = card.get("aprs") or []
                apr = None
                for apr_obj in aprs:
                    apr_obj = apr_obj.to_dict() if hasattr(apr_obj, "to_dict") else apr_obj
                    if apr_obj.get("apr_type") in _PURCHASE_APR_TYPES:
                        apr = apr_obj.get("apr_percentage")
                        break
                min_payment = card.get("minimum_payment_amount")
                min_cents = int(round(min_payment * 100)) if min_payment is not None else None
                next_due = card.get("next_payment_due_date")
                due_day = next_due.day if next_due is not None else None
                is_overdue = card.get("is_overdue")
                last_payment = card.get("last_payment_date")
                last_stmt_balance = card.get("last_statement_balance")
                last_stmt_cents = int(round(last_stmt_balance * 100)) if last_stmt_balance is not None else None

                result = await conn.execute(
                    """
                    UPDATE accounts SET
                        apr_percent                  = COALESCE($2, apr_percent),
                        min_payment_cents            = COALESCE($3, min_payment_cents),
                        due_day                      = COALESCE($4, due_day),
                        is_overdue                   = COALESCE($5, is_overdue),
                        last_payment_date            = COALESCE($6, last_payment_date),
                        last_statement_balance_cents = COALESCE($7, last_statement_balance_cents),
                        last_synced_at               = NOW(),
                        updated_at                   = NOW()
                    WHERE plaid_account_id = $1 AND is_active = TRUE
                    """,
                    plaid_account_id, apr, min_cents, due_day, is_overdue,
                    last_payment, last_stmt_cents,
                )
                if result != "UPDATE 0":
                    updated += 1

            # --- Student loans ---
            for loan in liabilities.get("student") or []:
                loan = loan.to_dict() if hasattr(loan, "to_dict") else loan
                plaid_account_id = loan.get("account_id", "")
                apr = loan.get("interest_rate_percentage")
                min_payment = loan.get("minimum_payment_amount")
                min_cents = int(round(min_payment * 100)) if min_payment is not None else None
                next_due = loan.get("next_payment_due_date")
                due_day = next_due.day if next_due is not None else None
                is_overdue = loan.get("is_overdue")
                payoff = loan.get("expected_payoff_date")
                ytd_interest = loan.get("ytd_interest_paid")
                ytd_cents = int(round(ytd_interest * 100)) if ytd_interest is not None else None

                result = await conn.execute(
                    """
                    UPDATE accounts SET
                        apr_percent             = COALESCE($2, apr_percent),
                        min_payment_cents       = COALESCE($3, min_payment_cents),
                        due_day                 = COALESCE($4, due_day),
                        is_overdue              = COALESCE($5, is_overdue),
                        expected_payoff_date    = COALESCE($6, expected_payoff_date),
                        ytd_interest_paid_cents = COALESCE($7, ytd_interest_paid_cents),
                        last_synced_at          = NOW(),
                        updated_at              = NOW()
                    WHERE plaid_account_id = $1 AND is_active = TRUE
                    """,
                    plaid_account_id, apr, min_cents, due_day, is_overdue, payoff, ytd_cents,
                )
                if result != "UPDATE 0":
                    updated += 1

            # --- Mortgages ---
            for mortgage in liabilities.get("mortgage") or []:
                mortgage = mortgage.to_dict() if hasattr(mortgage, "to_dict") else mortgage
                plaid_account_id = mortgage.get("account_id", "")
                rate_obj = mortgage.get("interest_rate") or {}
                if hasattr(rate_obj, "to_dict"):
                    rate_obj = rate_obj.to_dict()
                apr = rate_obj.get("percentage")
                next_payment = mortgage.get("next_monthly_payment")
                min_cents = int(round(next_payment * 100)) if next_payment is not None else None
                next_due = mortgage.get("next_payment_due_date")
                due_day = next_due.day if next_due is not None else None
                payoff = mortgage.get("maturity_date")
                ytd_interest = mortgage.get("ytd_interest_paid")
                ytd_cents = int(round(ytd_interest * 100)) if ytd_interest is not None else None

                result = await conn.execute(
                    """
                    UPDATE accounts SET
                        apr_percent             = COALESCE($2, apr_percent),
                        min_payment_cents       = COALESCE($3, min_payment_cents),
                        due_day                 = COALESCE($4, due_day),
                        expected_payoff_date    = COALESCE($5, expected_payoff_date),
                        ytd_interest_paid_cents = COALESCE($6, ytd_interest_paid_cents),
                        last_synced_at          = NOW(),
                        updated_at              = NOW()
                    WHERE plaid_account_id = $1 AND is_active = TRUE
                    """,
                    plaid_account_id, apr, min_cents, due_day, payoff, ytd_cents,
                )
                if result != "UPDATE 0":
                    updated += 1

        return updated

    async def build_account_id_map(self) -> Dict[str, int]:
        """Return {plaid_account_id: internal_id} for all active accounts."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, plaid_account_id FROM accounts WHERE plaid_account_id IS NOT NULL"
            )
        return {r["plaid_account_id"]: r["id"] for r in rows}

    async def delete_sandbox_data(self) -> dict:
        """
        Delete all data that originated from the Plaid sandbox environment.

        Key principle: only transactions carry source='plaid_sandbox'. Everything else
        (accounts, recurring_streams, holdings) is identified indirectly — by which
        accounts participated in sandbox transactions. We resolve this BEFORE deleting
        any transactions so the FK chain stays consistent.

        Deletion order (respects FK constraints):
          1. Identify sandbox account IDs and plaid_item IDs (from sandbox transactions)
          2. transaction_tags / transaction_splits for sandbox transactions
          3. transactions WHERE source = 'plaid_sandbox'
          4. recurring_streams for sandbox accounts
          5. investment_holdings / orphaned securities for sandbox accounts
          6. net_worth_snapshots (all — balances were tainted by sandbox)
          7. plaid_sync_log for sandbox plaid_items
          8. accounts that are sandbox accounts
          9. plaid_items that are sandbox items

        Categories, tags, and budgets are never touched.
        """
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():

                # --- Step 1: resolve sandbox accounts and items BEFORE deleting txns ---
                # Sandbox account = any account that has at least one sandbox transaction.
                # We also include plaid accounts that have zero transactions (connected but
                # never yielded data) that belong to a plaid_item already identified as sandbox.
                sandbox_accounts = await conn.fetch(
                    """
                    SELECT DISTINCT account_id AS id
                    FROM transactions
                    WHERE source = 'plaid_sandbox'
                    """
                )
                sandbox_account_id_list = [r["id"] for r in sandbox_accounts]

                # Sandbox plaid_items = items whose accounts are in the sandbox account set
                if sandbox_account_id_list:
                    sandbox_items = await conn.fetch(
                        """
                        SELECT DISTINCT plaid_item_id
                        FROM accounts
                        WHERE id = ANY($1::int[])
                          AND plaid_item_id IS NOT NULL
                        """,
                        sandbox_account_id_list,
                    )
                    sandbox_item_id_list = [r["plaid_item_id"] for r in sandbox_items]

                    # Also pick up any plaid accounts with zero transactions under sandbox items
                    extra_accounts = await conn.fetch(
                        """
                        SELECT id FROM accounts
                        WHERE plaid_item_id = ANY($1::text[])
                          AND id != ALL($2::int[])
                        """,
                        sandbox_item_id_list,
                        sandbox_account_id_list,
                    )
                    sandbox_account_id_list += [r["id"] for r in extra_accounts]
                else:
                    sandbox_item_id_list = []

                # --- Step 2: sandbox transaction IDs ---
                sandbox_tx_ids = await conn.fetch(
                    "SELECT id FROM transactions WHERE source = 'plaid_sandbox'"
                )
                sandbox_tx_id_list = [r["id"] for r in sandbox_tx_ids]
                tx_count = len(sandbox_tx_id_list)

                if sandbox_tx_id_list:
                    await conn.execute(
                        "DELETE FROM transaction_tags WHERE transaction_id = ANY($1::int[])",
                        sandbox_tx_id_list,
                    )
                    await conn.execute(
                        "DELETE FROM transaction_splits WHERE parent_transaction_id = ANY($1::int[])",
                        sandbox_tx_id_list,
                    )
                    await conn.execute(
                        "DELETE FROM transactions WHERE source = 'plaid_sandbox'"
                    )

                account_count = len(sandbox_account_id_list)
                stream_count = 0

                if sandbox_account_id_list:
                    # --- Step 4: recurring streams ---
                    # Delete streams linked to sandbox accounts AND orphaned streams
                    # (account_id IS NULL) since all recurring data comes from Plaid —
                    # there are no manually-created recurring streams in V2.
                    stream_result = await conn.execute(
                        """
                        DELETE FROM recurring_streams
                        WHERE account_id = ANY($1::int[])
                           OR account_id IS NULL
                        """,
                        sandbox_account_id_list,
                    )
                    stream_count = int(stream_result.split()[-1])

                    # --- Step 5: investment holdings and orphaned securities ---
                    await conn.execute(
                        "DELETE FROM investment_holdings WHERE account_id = ANY($1::int[])",
                        sandbox_account_id_list,
                    )
                    await conn.execute(
                        """
                        DELETE FROM securities
                        WHERE plaid_security_id NOT IN (
                            SELECT DISTINCT security_id FROM investment_holdings
                        )
                        """
                    )

                # --- Step 6: net worth snapshots taken since the sandbox item was first connected.
                # Snapshots created before the sandbox item existed have clean production data.
                if sandbox_item_id_list:
                    nw_result = await conn.execute(
                        """
                        DELETE FROM net_worth_snapshots
                        WHERE snapshot_date >= (
                            SELECT MIN(connected_at)::date
                            FROM plaid_items
                            WHERE item_id = ANY($1::text[])
                        )
                        """,
                        sandbox_item_id_list,
                    )
                else:
                    nw_result = "DELETE 0"
                nw_count = int(nw_result.split()[-1])

                # Also include plaid_items that were connected but never synced
                # (no accounts exist yet, so they weren't caught above).
                orphan_items = await conn.fetch(
                    """
                    SELECT item_id FROM plaid_items
                    WHERE NOT EXISTS (
                        SELECT 1 FROM accounts a WHERE a.plaid_item_id = plaid_items.item_id
                    )
                    AND item_id != ALL($1::text[])
                    """,
                    sandbox_item_id_list if sandbox_item_id_list else [],
                )
                sandbox_item_id_list = sandbox_item_id_list + [r["item_id"] for r in orphan_items]

                item_count = len(sandbox_item_id_list)

                if sandbox_item_id_list:
                    # --- Step 7: plaid sync log ---
                    await conn.execute(
                        "DELETE FROM plaid_sync_log WHERE item_id = ANY($1::text[])",
                        sandbox_item_id_list,
                    )

                # --- Step 8: accounts ---
                if sandbox_account_id_list:
                    await conn.execute(
                        "DELETE FROM accounts WHERE id = ANY($1::int[])",
                        sandbox_account_id_list,
                    )

                # --- Step 9: plaid_items ---
                if sandbox_item_id_list:
                    await conn.execute(
                        "DELETE FROM plaid_items WHERE item_id = ANY($1::text[])",
                        sandbox_item_id_list,
                    )

        logger.info(
            "Sandbox data deleted: %d transactions, %d accounts, %d streams, "
            "%d net_worth_snapshots, %d plaid_items",
            tx_count, account_count, stream_count, nw_count, item_count,
        )
        return {
            "transactions_deleted": tx_count,
            "accounts_deleted": account_count,
            "recurring_streams_deleted": stream_count,
            "net_worth_snapshots_deleted": nw_count,
            "plaid_items_deleted": item_count,
        }
