"""
Detect which Plaid-exposed liability fields are missing on each account
after a sync and record a single audit-log entry whenever the set of
missing fields transitions for a given account.

Why this module exists
----------------------
Some institutions (Capital One is the canonical example — see
``docs/plaid.md#limited-liabilities-coverage``) never return APR or
``balances.limit`` for specific credit-card products, even when
``/liabilities/get`` succeeds with HTTP 200. Silent gaps make users
suspect a bug on our side. Writing per-sync audit rows would drown the
log, so we compare the current missing-set to the one cached on
``accounts.plaid_missing_fields`` and only log on transitions:

- ``[] -> ["apr", "credit_limit"]``  — bank stopped (or never) reporting.
- ``["apr"] -> []``                  — bank started reporting.
- ``["apr"] -> ["apr"]``              — noop, nothing written.

The UI consumes ``plaid_missing_fields`` via ``GET /api/accounts`` to
decide when to show the "Not reported by bank" hint and unlock the
manual-override inputs.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from web.audit import record as audit_record

logger = logging.getLogger(__name__)

# Account types we track. Credit cards can miss APR *and* credit_limit;
# loans typically only expose APR (no "credit_limit" as a concept).
_TRACKED_TYPES = frozenset({"credit", "loan"})

# Exposed for the audit metadata and UI. Order-stable for deterministic
# comparisons across syncs.
FIELD_APR = "apr"
FIELD_CREDIT_LIMIT = "credit_limit"


def compute_missing_fields(row: Dict[str, Any]) -> List[str]:
    """Return the deterministic list of Plaid fields missing for ``row``.

    ``row`` must expose at minimum ``type``, ``credit_limit_cents`` and
    ``apr_percent``. Accounts we don't track (depository, investment, …)
    always return ``[]`` so they never contribute to audit noise.
    """
    acct_type = (row.get("type") or "").lower()
    if acct_type not in _TRACKED_TYPES:
        return []

    missing: List[str] = []
    if row.get("apr_percent") is None:
        missing.append(FIELD_APR)
    if acct_type == "credit" and row.get("credit_limit_cents") is None:
        missing.append(FIELD_CREDIT_LIMIT)
    return missing


def _normalize_prev(value: Any) -> List[str]:
    """Decode the cached JSONB list into a canonical list[str]."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return []
        return [str(v) for v in parsed] if isinstance(parsed, list) else []
    return []


async def detect_and_record_missing(
    *,
    item_id: str,
    source: str,
    actor_user_id: Optional[int] = None,
) -> int:
    """Scan all tracked accounts for ``item_id`` and record transitions.

    Returns the number of accounts whose missing-set changed (i.e. the
    number of audit rows written).
    """
    from web.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.id, a.name, a.type,
                   a.credit_limit_cents, a.apr_percent,
                   a.plaid_missing_fields,
                   pi.institution_name
            FROM accounts a
            LEFT JOIN plaid_items pi ON pi.item_id = a.plaid_item_id
            WHERE a.plaid_item_id = $1
              AND a.is_active = TRUE
              AND a.type = ANY($2::text[])
            """,
            item_id,
            list(_TRACKED_TYPES),
        )

        changed = 0
        for row in rows:
            now = compute_missing_fields(dict(row))
            prev = _normalize_prev(row.get("plaid_missing_fields"))
            if now == prev:
                continue

            await conn.execute(
                """
                UPDATE accounts
                SET plaid_missing_fields = $2::jsonb, updated_at = NOW()
                WHERE id = $1
                """,
                row["id"],
                json.dumps(now),
            )

            try:
                await audit_record(
                    event_type="plaid.liabilities.missing_field",
                    source=source,
                    actor_user_id=actor_user_id,
                    target_kind="account",
                    target_id=str(row["id"]),
                    metadata={
                        "account_name": row.get("name"),
                        "account_type": row.get("type"),
                        "institution_name": row.get("institution_name"),
                        "missing_now": now,
                        "missing_prev": prev,
                    },
                )
            except Exception as exc:  # pragma: no cover — audit must never block sync
                logger.warning(
                    "audit_record failed for plaid.liabilities.missing_field: %s", exc
                )

            changed += 1

    return changed
