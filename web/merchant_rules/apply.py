"""Preview and apply-existing for merchant category rules (read-only preview; UPDATE category_id only)."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from web.db import get_pool

from .keys import display_merchant_label, merchant_key

# Whitelist: only Plaid-backed transaction rows (see plan).
_PLAID_SOURCES = ("plaid", "plaid_sandbox")


def _parse_rule_key(merchant_key: str) -> Tuple[str, str]:
    if merchant_key.startswith("name:"):
        return "name", merchant_key[len("name:") :]
    if merchant_key.startswith("eid:"):
        return "eid", merchant_key[len("eid:") :]
    raise ValueError("Invalid merchant_key prefix")


def _merchant_sql_params(kind: str, suffix: str) -> Tuple[str, list[Any]]:
    """Returns SQL fragment for WHERE (parametrized) and flat param list for *suffix parts.

    For ``name:`` keys we match against ``merchant_name`` first and fall back to
    ``display_title`` when Plaid did not supply a merchant (ACH / checks / bill
    pays). This mirrors the key-building priority in ``keys.py``.
    """
    if kind == "name":
        sql = """
            t.source = ANY($1::text[])
            AND lower(trim(COALESCE(NULLIF(t.merchant_name, ''), t.display_title, ''))) = $2
            AND (t.merchant_entity_id IS NULL OR trim(t.merchant_entity_id) = '')
        """
        return sql, [list(_PLAID_SOURCES), suffix]
    if kind == "eid":
        sql = """
            t.source = ANY($1::text[])
            AND lower(trim(COALESCE(t.merchant_entity_id, ''))) = $2
        """
        return sql, [list(_PLAID_SOURCES), suffix]
    raise ValueError("unknown kind")


async def preview_for_rule(merchant_key: str, category_id: int) -> Dict[str, Any]:
    kind, suffix = _parse_rule_key(merchant_key)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _preview_conn(conn, kind, suffix, category_id)


async def preview_match_count(
    merchant_entity_id: Optional[str],
    merchant_name: Optional[str],
) -> Dict[str, Any]:
    """
    Category-less preview: how many Plaid transactions currently match this
    merchant by name (or entity id)? Used by the UI to give immediate feedback
    while the user is still typing, before they pick a target category.

    Returns ``match_count`` and ``sample_merchant_names``. It does NOT compute
    eligible/skipped buckets because those depend on the target category.
    """
    mk = merchant_key(merchant_entity_id, merchant_name)
    if not mk:
        raise ValueError("merchant_entity_id or merchant_name required")
    kind, suffix = _parse_rule_key(mk)
    base_sql, base_params = _merchant_sql_params(kind, suffix)
    pool = await get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            f"SELECT COUNT(*)::bigint FROM transactions t WHERE {base_sql}",
            *base_params,
        )
        sample_sql = f"""
            SELECT DISTINCT trim(COALESCE(NULLIF(t.merchant_name, ''), t.display_title, '')) AS mn
            FROM transactions t
            WHERE {base_sql}
            AND trim(COALESCE(NULLIF(t.merchant_name, ''), t.display_title, '')) <> ''
            LIMIT 8
        """
        samples = [r["mn"] for r in await conn.fetch(sample_sql, *base_params)]
    return {
        "match_count": int(count or 0),
        "sample_merchant_names": samples,
        "merchant_key": mk,
        "display_label": display_merchant_label(mk),
    }


async def preview_for_draft(
    merchant_entity_id: Optional[str],
    merchant_name: Optional[str],
    category_id: int,
) -> Dict[str, Any]:
    mk = merchant_key(merchant_entity_id, merchant_name)
    if not mk:
        raise ValueError("merchant_entity_id or merchant_name required")
    kind, suffix = _parse_rule_key(mk)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _preview_conn(conn, kind, suffix, category_id)


async def _preview_conn(conn, kind: str, suffix: str, category_id: int) -> Dict[str, Any]:
    base_sql, base_params = _merchant_sql_params(kind, suffix)
    # eligible: base + splits/custom + distinct from target
    eligible_sql = f"""
        SELECT COUNT(*)::bigint FROM transactions t
        WHERE {base_sql}
        AND NOT EXISTS (SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id)
        AND (
            t.category_id IS NULL
            OR EXISTS (SELECT 1 FROM categories c WHERE c.id = t.category_id AND c.source = 'plaid_pfc')
        )
        AND t.category_id IS DISTINCT FROM $3
    """
    eligible_params = [*base_params, category_id]
    eligible = await conn.fetchval(eligible_sql, *eligible_params)

    # sample labels — prefer merchant_name, fall back to display_title for ACH rows
    sample_sql = f"""
        SELECT DISTINCT trim(COALESCE(NULLIF(t.merchant_name, ''), t.display_title, '')) AS mn
        FROM transactions t
        WHERE {base_sql}
        AND NOT EXISTS (SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id)
        AND (
            t.category_id IS NULL
            OR EXISTS (SELECT 1 FROM categories c WHERE c.id = t.category_id AND c.source = 'plaid_pfc')
        )
        AND t.category_id IS DISTINCT FROM $3
        AND trim(COALESCE(NULLIF(t.merchant_name, ''), t.display_title, '')) <> ''
        LIMIT 8
    """
    samples = [r["mn"] for r in await conn.fetch(sample_sql, *eligible_params)]

    # skipped: splits (loose merchant match for name/eid kind)
    sk_split_sql = f"""
        SELECT COUNT(*)::bigint FROM transactions t
        WHERE {base_sql}
        AND EXISTS (SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id)
    """
    skipped_splits = await conn.fetchval(sk_split_sql, *base_params)

    # skipped: custom category, no splits
    sk_custom_sql = f"""
        SELECT COUNT(*)::bigint FROM transactions t
        WHERE {base_sql}
        AND NOT EXISTS (SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id)
        AND t.category_id IS NOT NULL
        AND EXISTS (SELECT 1 FROM categories c WHERE c.id = t.category_id AND c.source = 'custom')
    """
    skipped_custom = await conn.fetchval(sk_custom_sql, *base_params)

    skipped_entity = 0
    if kind == "name":
        loose_sql = """
            t.source = ANY($1::text[])
            AND lower(trim(COALESCE(t.merchant_name, ''))) = $2
            AND trim(COALESCE(t.merchant_entity_id, '')) <> ''
        """
        skipped_entity = await conn.fetchval(
            f"SELECT COUNT(*)::bigint FROM transactions t WHERE {loose_sql}",
            list(_PLAID_SOURCES),
            suffix,
        )

    return {
        "eligible_count": int(eligible or 0),
        "skipped_splits_count": int(skipped_splits or 0),
        "skipped_custom_category_count": int(skipped_custom or 0),
        "skipped_has_entity_id_count": int(skipped_entity or 0),
        "sample_merchant_names": samples,
    }


async def apply_rule_to_transactions(rule_id: int) -> Dict[str, Any]:
    from .repo import MerchantRulesRepository

    repo = MerchantRulesRepository()
    rule = await repo.get_rule(rule_id)
    if not rule:
        raise ValueError("Rule not found")

    merchant_key = rule["merchant_key"]
    category_id = int(rule["category_id"])
    kind, suffix = _parse_rule_key(merchant_key)

    pool = await get_pool()
    updated = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", rule_id)
            base_sql, base_params = _merchant_sql_params(kind, suffix)
            update_sql = f"""
                UPDATE transactions t
                SET category_id = $U, updated_at = NOW()
                WHERE {base_sql}
                AND NOT EXISTS (SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id)
                AND (
                    t.category_id IS NULL
                    OR EXISTS (SELECT 1 FROM categories c WHERE c.id = t.category_id AND c.source = 'plaid_pfc')
                )
                AND t.category_id IS DISTINCT FROM $U
            """
            u_sql = update_sql.replace("$U", "$3", 2)
            params = [*base_params, category_id]
            status = await conn.execute(u_sql, *params)
            parts = (status or "").split()
            updated = int(parts[-1]) if parts and parts[-1].isdigit() else 0

        prev = await _preview_conn(conn, kind, suffix, category_id)
        prev["updated_count"] = updated
        prev["merchant_key"] = merchant_key
        prev["display_label"] = display_merchant_label(merchant_key)
        return prev
