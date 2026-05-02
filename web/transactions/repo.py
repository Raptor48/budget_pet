"""
TransactionsRepository — DB operations for transactions + splits.
Uses shared asyncpg pool.
"""
import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from web.db import get_pool
from web.merchant_rules.aliases import alias_join_sql

logger = logging.getLogger(__name__)


def _apply_alias_inplace(rows: List[Dict[str, Any]]) -> None:
    """Override ``display_title`` with the user's merchant alias when present.

    The alias is layered on read so a rename instantly applies to every
    historical row of the same merchant_key. ``merchant_alias`` stays in the
    response so the UI can render an "aliased" affordance and offer a quick
    revert. ``display_title`` in the DB remains the auto-normalized value.
    """
    for r in rows:
        alias = r.get("merchant_alias")
        if alias:
            r["display_title"] = alias


class TransactionsRepository:
    async def _pool(self):
        return await get_pool()

    async def list_transactions(
        self,
        month: Optional[str] = None,
        account_id: Optional[int] = None,
        category_id: Optional[int] = None,
        parent_category_id: Optional[int] = None,
        tag_id: Optional[int] = None,
        search: Optional[str] = None,
        channel: Optional[str] = None,
        pending_only: Optional[bool] = None,
        source: Optional[str] = None,
        user_id: Optional[int] = None,
        viewer_user_id: Optional[int] = None,
        transaction_class: Optional[str] = None,
        exclude_internal_transfers: Optional[bool] = None,
        limit: int = 200,
        offset: int = 0,
        omit_heavy_fields: bool = True,
        exclude_plaid_sandbox: bool = False,
    ) -> List[Dict[str, Any]]:
        conditions = ["1=1"]
        params: List[Any] = []
        idx = 1

        if month:
            month_start = date.fromisoformat(f"{month}-01")
            conditions.append(f"COALESCE(t.authorized_date, t.date) >= ${idx}::date")
            params.append(month_start)
            idx += 1
            conditions.append(f"COALESCE(t.authorized_date, t.date) < (${idx}::date + INTERVAL '1 month')")
            params.append(month_start)
            idx += 1

        if account_id is not None:
            conditions.append(f"t.account_id = ${idx}")
            params.append(account_id)
            idx += 1

        if category_id is not None:
            # Match transactions whose own category OR any split's category equals the filter
            conditions.append(
                f"(t.category_id = ${idx} OR EXISTS ("
                f"SELECT 1 FROM transaction_splits ts "
                f"WHERE ts.parent_transaction_id = t.id AND ts.category_id = ${idx}"
                f"))"
            )
            params.append(category_id)
            idx += 1

        if parent_category_id is not None:
            # Roll a primary PFC bucket up: include the parent itself plus every
            # detailed PFC child linked via categories.parent_id. Mirrors the
            # COALESCE(parent_id, id) rule used in /api/reports/by-category so
            # the drill-down in Reports matches the bucket totals exactly
            # (split-aware, same semantics as category_id above).
            conditions.append(
                f"("
                f"t.category_id IN ("
                f"SELECT id FROM categories WHERE id = ${idx} OR parent_id = ${idx}"
                f") OR EXISTS ("
                f"SELECT 1 FROM transaction_splits ts "
                f"WHERE ts.parent_transaction_id = t.id "
                f"AND ts.category_id IN ("
                f"SELECT id FROM categories WHERE id = ${idx} OR parent_id = ${idx}"
                f")"
                f"))"
            )
            params.append(parent_category_id)
            idx += 1

        if tag_id is not None:
            conditions.append(
                f"EXISTS (SELECT 1 FROM transaction_tags tt WHERE tt.transaction_id = t.id AND tt.tag_id = ${idx})"
            )
            params.append(tag_id)
            idx += 1

        if search:
            conditions.append(
                f"(t.merchant_name ILIKE ${idx} OR t.name ILIKE ${idx})"
            )
            params.append(f"%{search}%")
            idx += 1

        if channel:
            conditions.append(f"t.payment_channel = ${idx}")
            params.append(channel)
            idx += 1

        if pending_only is not None:
            conditions.append(f"t.is_pending = ${idx}")
            params.append(pending_only)
            idx += 1

        if source:
            conditions.append(f"t.source = ${idx}")
            params.append(source)
            idx += 1

        if transaction_class is not None:
            conditions.append(f"t.transaction_class = ${idx}")
            params.append(transaction_class)
            idx += 1

        # Hide intra-family transfers from the Transactions list when the
        # caller opted in. Driven by the "Show internal transactions" toggle
        # on the frontend (default OFF) — the Reports endpoints already
        # exclude this class via `transaction_class = 'expense' | 'income'`,
        # but the raw list historically returned every row.
        if exclude_internal_transfers:
            conditions.append("t.transaction_class <> 'internal_transfer'")

        if user_id is not None:
            conditions.append(f"a.user_id = ${idx}")
            params.append(user_id)
            idx += 1

        if exclude_plaid_sandbox:
            conditions.append("(t.source IS NULL OR t.source <> 'plaid_sandbox')")

        # Hide private transactions that belong to other users.
        # viewer_user_id=None means no filtering (internal calls or tests).
        if viewer_user_id is not None:
            conditions.append(
                f"(NOT t.is_private OR EXISTS ("
                f"SELECT 1 FROM accounts _a WHERE _a.id = t.account_id AND _a.user_id = ${idx}"
                f"))"
            )
            params.append(viewer_user_id)
            idx += 1

        where = " AND ".join(conditions)
        params.append(limit)
        params.append(offset)

        if omit_heavy_fields:
            select_tx = """
                SELECT t.id,
                       t.plaid_transaction_id,
                       t.account_id,
                       t.category_id,
                       t.amount_cents,
                       t.currency,
                       t.date,
                       t.authorized_date,
                       t.datetime,
                       t.authorized_datetime,
                       t.name,
                       t.merchant_name,
                       t.merchant_entity_id,
                       t.logo_url,
                       t.website,
                       t.payment_channel,
                       t.pfc_primary,
                       t.pfc_detailed,
                       t.pfc_confidence,
                       t.pfc_icon_url,
                       NULL::jsonb AS counterparties,
                       NULL::jsonb AS location,
                       NULL::jsonb AS payment_meta,
                       t.is_pending,
                       t.is_private,
                       t.is_internal_transfer,
                       t.is_internal_transfer_manual,
                       t.transaction_class,
                       t.manual_class_override,
                       t.source,
                       t.user_note,
                       t.display_title,
                       t.created_at,
                       t.updated_at,
                       a.name     AS account_name,
                       a.mask     AS account_mask,
                       u.username AS owner_username,
                       ma.display_name AS merchant_alias,
                       EXISTS(SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id) AS has_splits,
                       EXISTS(SELECT 1 FROM receipts r WHERE r.transaction_id = t.id) AS has_receipt
                FROM transactions t
            """
        else:
            select_tx = """
                SELECT t.*,
                       a.name     AS account_name,
                       a.mask     AS account_mask,
                       u.username AS owner_username,
                       ma.display_name AS merchant_alias,
                       EXISTS(SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id) AS has_splits,
                       EXISTS(SELECT 1 FROM receipts r WHERE r.transaction_id = t.id) AS has_receipt
                FROM transactions t
            """

        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                {select_tx}
                LEFT JOIN accounts a ON a.id = t.account_id
                LEFT JOIN users u ON a.user_id = u.id
                {alias_join_sql("t", "ma")}
                WHERE {where}
                ORDER BY COALESCE(t.authorized_date, t.date) DESC, t.id DESC
                LIMIT ${idx} OFFSET ${idx + 1}
                """,
                *params,
            )
        out = [dict(r) for r in rows]
        _apply_alias_inplace(out)
        return out

    async def get_date_range(
        self,
        user_id: Optional[int] = None,
        viewer_user_id: Optional[int] = None,
        exclude_plaid_sandbox: bool = False,
    ) -> Dict[str, Optional[date]]:
        """
        Return the earliest and latest transaction dates visible to the caller.

        Applies the same ownership / privacy / sandbox filters as ``list_transactions``
        so the resulting range matches what the user can actually see in the UI.
        Returns ``{"earliest": None, "latest": None}`` when no transactions match.
        """
        conditions: List[str] = ["1=1"]
        params: List[Any] = []
        idx = 1

        if user_id is not None:
            conditions.append(f"a.user_id = ${idx}")
            params.append(user_id)
            idx += 1

        if exclude_plaid_sandbox:
            conditions.append("(t.source IS NULL OR t.source <> 'plaid_sandbox')")

        if viewer_user_id is not None:
            conditions.append(
                f"(NOT t.is_private OR EXISTS ("
                f"SELECT 1 FROM accounts _a WHERE _a.id = t.account_id AND _a.user_id = ${idx}"
                f"))"
            )
            params.append(viewer_user_id)
            idx += 1

        where = " AND ".join(conditions)
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT MIN(COALESCE(t.authorized_date, t.date)) AS earliest,
                       MAX(COALESCE(t.authorized_date, t.date)) AS latest
                FROM transactions t
                LEFT JOIN accounts a ON a.id = t.account_id
                WHERE {where}
                """,
                *params,
            )
        if row is None:
            return {"earliest": None, "latest": None}
        return {"earliest": row["earliest"], "latest": row["latest"]}

    async def get_transaction(
        self, transaction_id: int, viewer_user_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT t.*,
                       a.name     AS account_name,
                       a.mask     AS account_mask,
                       u.username AS owner_username,
                       a.user_id  AS account_user_id,
                       ma.display_name AS merchant_alias,
                       EXISTS(SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id) AS has_splits,
                       EXISTS(SELECT 1 FROM receipts r WHERE r.transaction_id = t.id) AS has_receipt
                FROM transactions t
                LEFT JOIN accounts a ON a.id = t.account_id
                LEFT JOIN users u ON a.user_id = u.id
                {alias_join_sql("t", "ma")}
                WHERE t.id = $1
                """,
                transaction_id,
            )
        if not row:
            return None
        result = dict(row)
        # Return None (treat as not found) if the transaction is private and
        # belongs to a different user. This prevents leaking existence via 403.
        if (
            viewer_user_id is not None
            and result.get("is_private")
            and result.get("account_user_id") != viewer_user_id
        ):
            return None
        _apply_alias_inplace([result])
        return result

    async def get_tags_for_transaction(self, transaction_id: int) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT tg.* FROM tags tg
                JOIN transaction_tags tt ON tt.tag_id = tg.id
                WHERE tt.transaction_id = $1
                ORDER BY tg.name
                """,
                transaction_id,
            )
        return [dict(r) for r in rows]

    async def get_splits_for_transaction(self, transaction_id: int) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM transaction_splits WHERE parent_transaction_id = $1 ORDER BY id",
                transaction_id,
            )
        return [dict(r) for r in rows]

    async def get_tags_for_transaction_ids(
        self, transaction_ids: List[int]
    ) -> Dict[int, List[Dict[str, Any]]]:
        """Bulk-load tags for many transactions (one query)."""
        if not transaction_ids:
            return {}
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT tt.transaction_id, tg.id, tg.name, tg.color, tg.created_at
                FROM transaction_tags tt
                JOIN tags tg ON tg.id = tt.tag_id
                WHERE tt.transaction_id = ANY($1::int[])
                ORDER BY tt.transaction_id, tg.name
                """,
                transaction_ids,
            )
        out: Dict[int, List[Dict[str, Any]]] = {}
        for r in rows:
            tid = r["transaction_id"]
            out.setdefault(tid, []).append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "color": r["color"],
                    "created_at": r["created_at"],
                }
            )
        return out

    async def get_splits_for_transaction_ids(
        self, transaction_ids: List[int]
    ) -> Dict[int, List[Dict[str, Any]]]:
        """Bulk-load splits for many transactions (one query)."""
        if not transaction_ids:
            return {}
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM transaction_splits
                WHERE parent_transaction_id = ANY($1::int[])
                ORDER BY parent_transaction_id, id
                """,
                transaction_ids,
            )
        out: Dict[int, List[Dict[str, Any]]] = {}
        for r in rows:
            tid = r["parent_transaction_id"]
            out.setdefault(tid, []).append(dict(r))
        return out

    async def create_cash_transaction(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a cash transaction and adjust the cash wallet balance in one DB transaction."""
        pool = await self._pool()
        account_id = int(data["account_id"])
        amount_cents = int(data["amount_cents"])
        async with pool.acquire() as conn:
            async with conn.transaction():
                w = await conn.fetchrow(
                    "SELECT id, plaid_account_id FROM accounts WHERE id = $1 FOR UPDATE",
                    account_id,
                )
                if not w or w["plaid_account_id"] is not None:
                    raise ValueError("Invalid cash wallet for transaction")
                from web.transactions.display import normalize_transaction_title

                display_title = normalize_transaction_title(data)
                row = await conn.fetchrow(
                    """
                    INSERT INTO transactions (
                        plaid_transaction_id, account_id, category_id,
                        amount_cents, currency, date, authorized_date,
                        datetime, authorized_datetime, name, merchant_name,
                        merchant_entity_id, logo_url, website, payment_channel,
                        pfc_primary, pfc_detailed, pfc_confidence, pfc_icon_url,
                        counterparties, location, payment_meta,
                        is_pending, source, user_note, display_title
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                        $16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26
                    )
                    ON CONFLICT (plaid_transaction_id) DO UPDATE SET
                        account_id           = EXCLUDED.account_id,
                        category_id          = COALESCE(transactions.category_id, EXCLUDED.category_id),
                        amount_cents         = EXCLUDED.amount_cents,
                        date                 = EXCLUDED.date,
                        authorized_date      = EXCLUDED.authorized_date,
                        datetime             = EXCLUDED.datetime,
                        authorized_datetime  = EXCLUDED.authorized_datetime,
                        name                 = EXCLUDED.name,
                        merchant_name        = EXCLUDED.merchant_name,
                        merchant_entity_id   = EXCLUDED.merchant_entity_id,
                        logo_url             = EXCLUDED.logo_url,
                        website              = EXCLUDED.website,
                        payment_channel      = EXCLUDED.payment_channel,
                        pfc_primary          = EXCLUDED.pfc_primary,
                        pfc_detailed         = EXCLUDED.pfc_detailed,
                        pfc_confidence       = EXCLUDED.pfc_confidence,
                        pfc_icon_url         = EXCLUDED.pfc_icon_url,
                        counterparties       = EXCLUDED.counterparties,
                        location             = EXCLUDED.location,
                        payment_meta         = EXCLUDED.payment_meta,
                        is_pending           = EXCLUDED.is_pending,
                        source               = EXCLUDED.source,
                        display_title        = EXCLUDED.display_title,
                        updated_at           = NOW()
                    RETURNING *
                    """,
                    data.get("plaid_transaction_id"),
                    account_id,
                    data.get("category_id"),
                    amount_cents,
                    data.get("currency", "USD"),
                    data["date"],
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
                    data.get("source", "cash"),
                    data.get("user_note"),
                    display_title,
                )
                bal = await conn.fetchrow(
                    """
                    UPDATE accounts
                    SET current_balance_cents = current_balance_cents - $2,
                        updated_at = NOW()
                    WHERE id = $1 AND plaid_account_id IS NULL
                    RETURNING id
                    """,
                    account_id,
                    amount_cents,
                )
                if not bal:
                    raise ValueError("Cash wallet balance could not be updated")
                # Compute the four-class classification in-line so the new
                # row enters aggregates with the correct ``transaction_class``
                # from tick one. Cash transactions never pair with another
                # account, so ``classify_one_on_insert`` almost always
                # returns ``expense`` (or ``income`` for user-categorized
                # refunds) — the helper is kept generic so future manual
                # overrides from the cash UI flow through the same code.
                try:
                    from web.classification.classifier import classify_one_on_insert

                    await classify_one_on_insert(conn, row["id"])
                    row = await conn.fetchrow(
                        "SELECT * FROM transactions WHERE id = $1", row["id"]
                    )
                except Exception:
                    logger.exception(
                        "Cash POST: classification failed for id=%s; leaving default",
                        row["id"],
                    )
        return dict(row)

    async def update_transaction(
        self, transaction_id: int, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        allowed = {
            "category_id",
            "user_note",
            "merchant_name",
            "is_private",
            "is_internal_transfer",
            "transaction_class",
            # Owner-only override of the bank-reported amount. The route
            # layer is responsible for gating this on ``is_owner``; the
            # repo just enforces invariants below (positive int, no
            # outstanding splits) and stamps ``manual_amount_override``
            # so the next Plaid sync doesn't undo the change.
            "amount_cents",
        }
        fields = {k: v for k, v in data.items() if k in allowed}
        if not fields:
            return await self.get_transaction(transaction_id)

        # ------------------------------------------------------------------
        # amount_cents — input validation + invariants. Done up front so we
        # never reach the SET clause with a value that would corrupt
        # downstream aggregates or break the splits invariant.
        # ------------------------------------------------------------------
        if "amount_cents" in fields:
            try:
                new_amount = int(fields["amount_cents"])
            except (TypeError, ValueError) as exc:
                raise ValueError("amount_cents must be an integer") from exc
            if new_amount == 0:
                # Zero amount has no meaning in any of our aggregates and is
                # almost certainly a UX mistake (empty input → 0 → silent
                # wipeout of the row's contribution to budgets / reports).
                raise ValueError("amount_cents must not be zero")
            fields["amount_cents"] = new_amount

            # Splits invariant — ``SUM(splits.amount_cents) == parent.amount_cents``
            # is enforced by ``SplitsRepository.set_splits``. If splits already
            # exist, an amount edit would silently leave them mismatched and
            # the next ``set_splits`` call would reject the row. Reject the
            # edit up front with a clear message instead, so the user knows
            # to clear splits first.
            pool = await self._pool()
            async with pool.acquire() as conn:
                has_splits = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM transaction_splits "
                    "WHERE parent_transaction_id = $1)",
                    transaction_id,
                )
            if has_splits:
                raise ValueError(
                    "Cannot edit amount on a transaction with splits — "
                    "delete the splits first, then re-create them after "
                    "the new amount is saved."
                )

            # Stamp the protection flag so Plaid sync won't overwrite this
            # value on the next ``/transactions/sync`` upsert. Mirrors the
            # ``manual_class_override`` / ``is_internal_transfer_manual``
            # pattern (see web/plaid/repo.py upsert).
            fields["manual_amount_override"] = True

        # Normalize the two ways a client can express "force this row to
        # internal_transfer" into a single ``manual_class_override`` write.
        # ``transaction_class`` (new, four-class API) always wins; the
        # legacy ``is_internal_transfer`` boolean is kept for backwards
        # compatibility — existing mobile builds and the old transactions
        # menu still ship with a simple toggle.
        class_override: Optional[str] = None
        if "transaction_class" in fields:
            value = fields.pop("transaction_class")
            from web.classification.classifier import ALL_CLASSES

            if value is None:
                class_override = None
            elif value not in ALL_CLASSES:
                raise ValueError(f"Unknown transaction_class: {value}")
            else:
                class_override = value
            # ``manual_class_override`` is the source of truth; the
            # legacy binary bit is kept in sync so older readers still
            # work (and so our own aggregates can predicate on either
            # column during the transition).
            fields["manual_class_override"] = class_override
            fields["transaction_class"] = class_override or "uncategorized"
            if class_override == "internal_transfer":
                fields["is_internal_transfer"] = True
                fields["is_internal_transfer_manual"] = True
            elif class_override is None:
                fields["is_internal_transfer_manual"] = False
            else:
                fields["is_internal_transfer"] = False
                fields["is_internal_transfer_manual"] = False
        elif "is_internal_transfer" in fields:
            # Legacy path: toggling the boolean also sets the override +
            # manual sentinel so the auto re-classifier never overwrites
            # the user's choice on subsequent rescans.
            fields["is_internal_transfer_manual"] = True
            fields["manual_class_override"] = (
                "internal_transfer" if fields["is_internal_transfer"] else None
            )
            if fields["is_internal_transfer"]:
                fields["transaction_class"] = "internal_transfer"

        reclassify_after = (
            "category_id" in fields
            and "transaction_class" not in fields
            and "manual_class_override" not in fields
        )

        set_clause = ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(fields.keys()))
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE transactions SET {set_clause}, updated_at = NOW() WHERE id = $1 RETURNING *",
                transaction_id,
                *fields.values(),
            )
            if row and "merchant_name" in fields:
                from web.transactions.display import normalize_transaction_title

                updated = dict(row)
                new_title = normalize_transaction_title(updated)
                if new_title != updated.get("display_title"):
                    row2 = await conn.fetchrow(
                        "UPDATE transactions SET display_title = $2 WHERE id = $1 RETURNING *",
                        transaction_id,
                        new_title,
                    )
                    if row2:
                        row = row2
            # A category change can flip the class (e.g. user re-assigns a
            # paycheck from Uncategorized to Wages). Re-run the classifier
            # for just this row so the Income / Expenses tabs reflect the
            # new taxonomy without waiting for the next sync.
            if row and reclassify_after:
                try:
                    from web.classification.classifier import classify_one_on_insert

                    await classify_one_on_insert(conn, transaction_id)
                    row = await conn.fetchrow(
                        "SELECT * FROM transactions WHERE id = $1", transaction_id
                    )
                except Exception:
                    logger.exception(
                        "PATCH reclassify failed for id=%s; keeping previous class",
                        transaction_id,
                    )
        return dict(row) if row else None

    async def delete_transaction(self, transaction_id: int) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id, account_id, amount_cents, source
                    FROM transactions
                    WHERE id = $1 AND source NOT IN ('plaid', 'plaid_sandbox')
                    FOR UPDATE
                    """,
                    transaction_id,
                )
                if not row:
                    return False
                if row["source"] == "cash":
                    bal = await conn.fetchrow(
                        """
                        UPDATE accounts
                        SET current_balance_cents = current_balance_cents + $2,
                            updated_at = NOW()
                        WHERE id = $1 AND plaid_account_id IS NULL
                        RETURNING id
                        """,
                        row["account_id"],
                        row["amount_cents"],
                    )
                    if not bal:
                        raise ValueError("Cash wallet balance could not be reverted")
                result = await conn.execute("DELETE FROM transactions WHERE id = $1", transaction_id)
        return result != "DELETE 0"

    async def add_tag(self, transaction_id: int, tag_id: int) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO transaction_tags (transaction_id, tag_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                transaction_id,
                tag_id,
            )

    async def remove_tag(self, transaction_id: int, tag_id: int) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM transaction_tags WHERE transaction_id = $1 AND tag_id = $2",
                transaction_id,
                tag_id,
            )
        return result != "DELETE 0"

    async def delete_by_plaid_ids(self, plaid_ids: List[str]) -> int:
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
