"""
Internal-transfer classifier.

A transaction is an "internal transfer" when it is money moving between
family members (e.g. a Zelle payment between spouses) rather than an actual
income or expense for the family. When *both* sides of a transfer are
synced, naïve aggregation double-counts: the sender's TRANSFER_OUT looks
like an expense, and the recipient's subsequent purchase looks like a
second, independent expense. Flagging one (or both) sides as internal keeps
family totals consistent.

The classifier is intentionally simple: it matches Plaid ``TRANSFER_IN`` /
``TRANSFER_OUT`` transactions against a flat, family-wide list of
counterparty names (configured from the Transactions page settings dialog).
This works because every typical Zelle-style inbound transfer surfaces the
other party's legal name in ``merchant_name``, ``name`` or
``counterparties[*].name``; a substring match against the normalized value
is enough to catch the common formats banks emit ("Zelle payment from
ANASTASIIA STOLPOVSKAIA", "ZELLE FROM STOLPOVSKAIA A", ...).

Aggregated queries filter rows where ``is_internal_transfer = TRUE``. The
companion ``is_internal_transfer_manual`` column protects explicit user
decisions from being overwritten by the auto classifier on re-scan.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, List, Optional, Sequence

import asyncpg

logger = logging.getLogger(__name__)


# Plaid PFC primary values that represent money transfers (Zelle, ACH, wire,
# Venmo, savings-to-checking, ...). Any other PFC is never auto-flagged even
# if the configured name happens to appear in the description, because
# regular purchases at a merchant named after a family member are almost
# always real expenses.
_TRANSFER_PFC_PRIMARIES = frozenset({"TRANSFER_IN", "TRANSFER_OUT"})


# Boilerplate that US banks slap in front of the actual counterparty name
# on Zelle-style transfers. Stripping it before the substring match lets a
# single configured alias match both directions ("Zelle Payment From J DOE"
# and "Zelle Payment To J DOE"). Applied after uppercasing the string.
_NAME_NOISE_PATTERNS = (
    re.compile(r"\bZELLE\s+PAYMENT\s+(?:FROM|TO)\b"),
    re.compile(r"\bZELLE\s+(?:FROM|TO)\b"),
    re.compile(r"\bZELLE\s+TRANSFER\s+(?:FROM|TO)\b"),
    re.compile(r"\bZELLE\s+TRANSFER\b"),
    re.compile(r"\bZELLE\s+PAYMENT\b"),
    re.compile(r"\bZELLE\b"),
    re.compile(r"\bP2P\s+(?:TRANSFER|PAYMENT)\b"),
    re.compile(r"\bACH\s+(?:TRANSFER|CREDIT|DEBIT|PAYMENT)\b"),
    re.compile(r"\bWIRE\s+(?:TRANSFER|CREDIT|DEBIT)\b"),
)

_COLLAPSE_WS = re.compile(r"\s+")


def normalize_name(raw: Optional[str]) -> str:
    """
    Canonicalize a name for substring matching.

    Uppercases, strips boilerplate wrapper phrases banks emit ("Zelle
    Payment From X"), and collapses whitespace. Returns ``""`` for empty
    input so callers can compare safely. The same transformation is
    applied to the configured names, so matching is tolerant to casing
    and punctuation differences between the list and what Plaid returns.
    """
    if not raw:
        return ""
    s = str(raw).upper().strip()
    for pat in _NAME_NOISE_PATTERNS:
        s = pat.sub(" ", s)
    s = _COLLAPSE_WS.sub(" ", s).strip()
    return s


def normalize_names(raw_names: Iterable[Optional[str]]) -> List[str]:
    """Normalize + dedupe a list of configured names; drop empties."""
    seen: dict[str, None] = {}
    for name in raw_names:
        key = normalize_name(name)
        if key and key not in seen:
            seen[key] = None
    return list(seen.keys())


def _counterparty_names(counterparties: Any) -> List[str]:
    """Extract the ``name`` field from a Plaid counterparties list."""
    if counterparties is None:
        return []
    if isinstance(counterparties, str):
        try:
            counterparties = json.loads(counterparties)
        except (json.JSONDecodeError, ValueError):
            return []
    if not isinstance(counterparties, list):
        return []
    out: List[str] = []
    for cp in counterparties:
        if isinstance(cp, dict):
            n = cp.get("name")
            if n:
                out.append(str(n))
    return out


def classify_internal_transfer(
    *,
    pfc_primary: Optional[str],
    merchant_name: Optional[str] = None,
    name: Optional[str] = None,
    counterparties: Any = None,
    normalized_names: Sequence[str],
) -> bool:
    """
    Decide whether a transaction should be auto-flagged as internal transfer.

    Rules:
      1. Must be a transfer (``pfc_primary in TRANSFER_IN/OUT``). Payments
         to a merchant that coincidentally shares a name with a relative
         stay expenses.
      2. Some configured name must appear as a substring of the normalized
         ``merchant_name``, ``name`` or any ``counterparties[*].name``. The
         common banks (Chase Zelle) always put the other party's legal name
         in at least one of these fields.
    """
    if not normalized_names:
        return False
    if (pfc_primary or "").upper() not in _TRANSFER_PFC_PRIMARIES:
        return False

    haystacks = [
        normalize_name(merchant_name),
        normalize_name(name),
    ]
    haystacks.extend(normalize_name(n) for n in _counterparty_names(counterparties))

    return any(
        needle and any(needle in hay for hay in haystacks if hay)
        for needle in normalized_names
    )


async def get_configured_names(conn: asyncpg.Connection) -> List[str]:
    """
    Fetch the family-wide list of internal-transfer names from app_settings.

    Returns an empty list when the column is missing (pre-migration) or the
    value is NULL. Callers should treat an empty list as "auto-classification
    disabled" — they skip the scan entirely rather than matching everything.
    """
    try:
        row = await conn.fetchrow(
            "SELECT internal_transfer_names FROM app_settings WHERE id = 1"
        )
    except asyncpg.UndefinedColumnError:
        return []
    if not row:
        return []
    raw = row["internal_transfer_names"] or []
    return normalize_names(raw)


async def rescan_internal_transfers(
    conn: asyncpg.Connection,
    *,
    horizon_days: Optional[int] = 90,
) -> int:
    """
    Re-classify existing transactions against the current names list.

    Only TRANSFER_IN/TRANSFER_OUT rows whose flag was *not* set manually by
    a user are touched; manual decisions are always preserved. Returns the
    number of rows whose flag value changed. ``horizon_days=None`` scans
    the entire history.

    Matching is performed in Python so the substring + noise-stripping
    rules stay in one place. For a typical family (~1k transfer txns over
    a year) this is well under a second; if we ever outgrow that we can
    push the predicate down into SQL.
    """
    normalized = await get_configured_names(conn)

    params: list = [list(_TRANSFER_PFC_PRIMARIES)]
    where_date = ""
    if horizon_days is not None and horizon_days > 0:
        params.append(int(horizon_days))
        where_date = (
            f" AND COALESCE(authorized_date, date) >= "
            f"CURRENT_DATE - ${len(params)}::int * INTERVAL '1 day'"
        )

    rows = await conn.fetch(
        f"""
        SELECT id, pfc_primary, merchant_name, name, counterparties,
               is_internal_transfer
        FROM transactions
        WHERE is_internal_transfer_manual = FALSE
          AND pfc_primary = ANY($1::text[])
          {where_date}
        """,
        *params,
    )

    updates: list[tuple[int, bool]] = []
    for r in rows:
        new_flag = classify_internal_transfer(
            pfc_primary=r["pfc_primary"],
            merchant_name=r["merchant_name"],
            name=r["name"],
            counterparties=r["counterparties"],
            normalized_names=normalized,
        )
        if bool(r["is_internal_transfer"]) != new_flag:
            updates.append((r["id"], new_flag))

    if not updates:
        return 0

    await conn.executemany(
        """
        UPDATE transactions
        SET is_internal_transfer = $2, updated_at = NOW()
        WHERE id = $1 AND is_internal_transfer_manual = FALSE
        """,
        updates,
    )
    logger.info(
        "Internal-transfer rescan: %d rows reclassified (horizon_days=%s)",
        len(updates),
        horizon_days,
    )
    return len(updates)
