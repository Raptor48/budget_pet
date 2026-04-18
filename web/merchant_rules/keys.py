"""Single source of truth for merchant_key normalization (import, preview, apply).

Key-building priority (first non-empty wins):
    1. ``merchant_entity_id`` — Plaid's stable merchant identifier (``eid:<id>``).
    2. ``merchant_name``     — Plaid's enriched merchant label (``name:<lower>``).
    3. ``fallback_display``  — normalized ``display_title`` of a transaction.
       Used for ACH / checks / bill-pays where Plaid did not supply a merchant
       but the user still wants to attach a rule to what they see in the UI
       (e.g. "Pmts Sec: Ind"). Also produces a ``name:`` key so that lookups
       fall through the same SQL branch as explicit merchant_name rules.
"""
from __future__ import annotations

from typing import Optional


def merchant_key(
    merchant_entity_id: Optional[str],
    merchant_name: Optional[str],
    fallback_display: Optional[str] = None,
) -> Optional[str]:
    eid = (merchant_entity_id or "").strip()
    if eid:
        return f"eid:{eid.lower()}"
    name = (merchant_name or "").strip()
    if name:
        return f"name:{name.lower()}"
    fd = (fallback_display or "").strip()
    if fd:
        return f"name:{fd.lower()}"
    return None


def display_merchant_label(merchant_key: str) -> str:
    if not merchant_key:
        return ""
    if merchant_key.startswith("name:"):
        return merchant_key[len("name:") :].strip() or merchant_key
    if merchant_key.startswith("eid:"):
        raw = merchant_key[len("eid:") :].strip()
        if len(raw) <= 12:
            return raw or merchant_key
        return f"{raw[:6]}…{raw[-4:]}"
    return merchant_key
