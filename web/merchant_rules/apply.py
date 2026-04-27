"""Preview and apply-existing for merchant category rules.

The ``description_contains`` filter is threaded through every helper here
so a "narrow" rule (Zelle + 'alla' → Rent) generates the same preview
shape and apply-existing semantics as a generic rule (Zelle → Transfer
Out). The SQL fragments below all use a single helper —
``_merchant_sql_params`` — so the WHERE clause stays consistent
across preview, apply, and lookup paths.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from web.db import get_pool

from .keys import display_merchant_label, merchant_key

# Whitelist: only Plaid-backed transaction rows (see plan).
_PLAID_SOURCES = ("plaid", "plaid_sandbox")


def _normalize_filter(value: Optional[str]) -> Optional[str]:
    """Same lower/strip rule the repo uses on write so a preview and the
    eventual apply-existing match exactly the same set of rows."""
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def _parse_rule_key(merchant_key: str) -> Tuple[str, str]:
    if merchant_key.startswith("name:"):
        return "name", merchant_key[len("name:") :]
    if merchant_key.startswith("eid:"):
        return "eid", merchant_key[len("eid:") :]
    raise ValueError("Invalid merchant_key prefix")


def _merchant_sql_params(
    kind: str,
    suffix: str,
    description_contains: Optional[str] = None,
) -> Tuple[str, list[Any]]:
    """Returns SQL fragment for WHERE (parametrized) and a flat param list.

    Three matching modes share this helper:

    * ``name``  → matches by merchant_name OR display_title (the existing
      ACH / checks fallback).
    * ``eid``   → matches by merchant_entity_id (Plaid's stable id).
    * ``description_contains`` (optional, AND'd onto either of the above)
      → narrows the match further by substring of ``name`` /
      ``display_title``. Pass ``None`` to skip — this preserves legacy
      "match every transaction with this merchant_key" semantics.
    """
    if kind == "name":
        sql = """
            t.source = ANY($1::text[])
            AND lower(trim(COALESCE(NULLIF(t.merchant_name, ''), t.display_title, ''))) = $2
            AND (t.merchant_entity_id IS NULL OR trim(t.merchant_entity_id) = '')
        """
        params: list[Any] = [list(_PLAID_SOURCES), suffix]
    elif kind == "eid":
        sql = """
            t.source = ANY($1::text[])
            AND lower(trim(COALESCE(t.merchant_entity_id, ''))) = $2
        """
        params = [list(_PLAID_SOURCES), suffix]
    else:
        raise ValueError("unknown kind")

    filt = _normalize_filter(description_contains)
    if filt:
        # Substring search against both the raw statement line (``name``)
        # and the cleaned-up UI title (``display_title``). Either match
        # qualifies the row. Both columns are lower-cased on the fly;
        # we accept the per-row cost in exchange for keeping the schema
        # untouched on transactions.
        params.append(filt)
        idx = len(params)
        sql += f"""
            AND (
                position(${idx} IN lower(COALESCE(t.name, ''))) > 0
                OR position(${idx} IN lower(COALESCE(t.display_title, ''))) > 0
            )
        """
    return sql, params


async def preview_for_rule(
    merchant_key: str,
    category_id: int,
    description_contains: Optional[str] = None,
) -> Dict[str, Any]:
    kind, suffix = _parse_rule_key(merchant_key)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _preview_conn(
            conn, kind, suffix, category_id, description_contains
        )


async def preview_match_count(
    merchant_entity_id: Optional[str],
    merchant_name: Optional[str],
    description_contains: Optional[str] = None,
) -> Dict[str, Any]:
    """Category-less preview: how many Plaid transactions currently match
    this merchant (optionally narrowed by description)?

    Returns ``match_count`` for the requested filter plus
    ``distinct_description_count`` — the number of distinct ``name``
    values for this merchant in the table. The UI uses the latter to
    decide whether to surface the "narrow with description" option in
    the smart popover (showing it for a merchant with only one distinct
    description would just be noise).
    """
    mk = merchant_key(merchant_entity_id, merchant_name)
    if not mk:
        raise ValueError("merchant_entity_id or merchant_name required")
    kind, suffix = _parse_rule_key(mk)
    base_sql, base_params = _merchant_sql_params(
        kind, suffix, description_contains
    )
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

        # Diversity probe — ignores ``description_contains`` so the UI
        # can detect "this merchant has 5 different descriptions, a
        # filter would be useful" even when the caller is previewing
        # with a filter already applied.
        unfiltered_sql, unfiltered_params = _merchant_sql_params(kind, suffix)
        distinct_count = await conn.fetchval(
            f"""
            SELECT COUNT(DISTINCT lower(COALESCE(t.name, t.display_title, '')))::bigint
            FROM transactions t
            WHERE {unfiltered_sql}
            """,
            *unfiltered_params,
        )
    return {
        "match_count": int(count or 0),
        "distinct_description_count": int(distinct_count or 0),
        "sample_merchant_names": samples,
        "merchant_key": mk,
        "display_label": display_merchant_label(mk),
    }


async def preview_for_draft(
    merchant_entity_id: Optional[str],
    merchant_name: Optional[str],
    category_id: int,
    description_contains: Optional[str] = None,
) -> Dict[str, Any]:
    mk = merchant_key(merchant_entity_id, merchant_name)
    if not mk:
        raise ValueError("merchant_entity_id or merchant_name required")
    kind, suffix = _parse_rule_key(mk)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _preview_conn(
            conn, kind, suffix, category_id, description_contains
        )


async def _preview_conn(
    conn,
    kind: str,
    suffix: str,
    category_id: int,
    description_contains: Optional[str] = None,
) -> Dict[str, Any]:
    base_sql, base_params = _merchant_sql_params(kind, suffix, description_contains)
    cat_idx = len(base_params) + 1
    # eligible: base + splits/custom + distinct from target
    eligible_sql = f"""
        SELECT COUNT(*)::bigint FROM transactions t
        WHERE {base_sql}
        AND NOT EXISTS (SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id)
        AND (
            t.category_id IS NULL
            OR EXISTS (SELECT 1 FROM categories c WHERE c.id = t.category_id AND c.source = 'plaid_pfc')
        )
        AND t.category_id IS DISTINCT FROM ${cat_idx}
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
        AND t.category_id IS DISTINCT FROM ${cat_idx}
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
        # Re-use the same description-filter when counting the "skipped
        # because the row HAS a Plaid entity id" bucket — otherwise a
        # narrow rule's diagnostics would over-count rows it would
        # never have matched anyway.
        loose_filt = _normalize_filter(description_contains)
        loose_sql = """
            t.source = ANY($1::text[])
            AND lower(trim(COALESCE(t.merchant_name, ''))) = $2
            AND trim(COALESCE(t.merchant_entity_id, '')) <> ''
        """
        loose_params: list[Any] = [list(_PLAID_SOURCES), suffix]
        if loose_filt:
            loose_params.append(loose_filt)
            loose_sql += f"""
                AND (
                    position(${len(loose_params)} IN lower(COALESCE(t.name, ''))) > 0
                    OR position(${len(loose_params)} IN lower(COALESCE(t.display_title, ''))) > 0
                )
            """
        skipped_entity = await conn.fetchval(
            f"SELECT COUNT(*)::bigint FROM transactions t WHERE {loose_sql}",
            *loose_params,
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
    description_contains = rule.get("description_contains")
    kind, suffix = _parse_rule_key(merchant_key)

    pool = await get_pool()
    updated = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", rule_id)
            base_sql, base_params = _merchant_sql_params(
                kind, suffix, description_contains
            )
            cat_idx = len(base_params) + 1
            update_sql = f"""
                UPDATE transactions t
                SET category_id = ${cat_idx}, updated_at = NOW()
                WHERE {base_sql}
                AND NOT EXISTS (SELECT 1 FROM transaction_splits ts WHERE ts.parent_transaction_id = t.id)
                AND (
                    t.category_id IS NULL
                    OR EXISTS (SELECT 1 FROM categories c WHERE c.id = t.category_id AND c.source = 'plaid_pfc')
                )
                AND t.category_id IS DISTINCT FROM ${cat_idx}
            """
            params: List[Any] = [*base_params, category_id]
            status = await conn.execute(update_sql, *params)
            parts = (status or "").split()
            updated = int(parts[-1]) if parts and parts[-1].isdigit() else 0

        prev = await _preview_conn(
            conn, kind, suffix, category_id, description_contains
        )
        prev["updated_count"] = updated
        prev["merchant_key"] = merchant_key
        prev["display_label"] = display_merchant_label(merchant_key)
        prev["description_contains"] = description_contains
        return prev
