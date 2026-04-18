"""Single source of truth for merchant_key normalization (import, preview, apply)."""
from __future__ import annotations

from typing import Optional


def merchant_key(merchant_entity_id: Optional[str], merchant_name: Optional[str]) -> Optional[str]:
    eid = (merchant_entity_id or "").strip()
    if eid:
        return f"eid:{eid.lower()}"
    name = (merchant_name or "").strip()
    if name:
        return f"name:{name.lower()}"
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
