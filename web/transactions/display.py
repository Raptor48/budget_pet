"""
Transaction display title normalization.

Plaid's raw `transactions.name` is typically a verbatim bank-statement string and
can contain ACH/POS metadata, long alphanumeric IDs, dates, and operator codes
that overflow UI elements and are not user-friendly. `merchant_name` is the
preferred Plaid enrichment, but it is missing for ACH transfers, internal
transfers, checks, and many bill payments.

`normalize_transaction_title` is the single source of truth used by both the
backend (CSV exports, insights, recurring streams) and the frontend (rendered as
`display_title`). The frontend mirror in `frontend/src/lib/transaction-display.ts`
must stay in sync with the rules below.

Priority of sources (first non-empty wins):
    1. `merchant_name` (Plaid enriched, already pretty)
    2. `counterparties[]` — first entry with type='merchant', otherwise the
       entry with the highest `confidence_level`.
    3. Hostname extracted from `website`.
    4. Heuristically cleaned `name`.
    5. Fallback "Transaction".
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List, Mapping, Optional


_MAX_LEN = 42

# Rank for confidence_level; higher = more confident. Mirrors Plaid PFC docs.
_CONFIDENCE_RANK = {
    "VERY_HIGH": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "UNKNOWN": 0,
    None: 0,
}

# Common bank-statement prefixes to strip (case-insensitive). Order matters:
# longer / more specific phrases are tried first to avoid leaving fragments
# like "TO" behind when "ACH CREDIT TO" is removed.
_PREFIXES = [
    r"REAL\s+TIME\s+TRANSFER\s+(?:RECD|RECEIVED)\s+FROM",
    r"REAL\s+TIME\s+TRANSFER\s+(?:SENT\s+TO|TO)",
    r"PURCHASE\s+AUTHORIZED\s+ON\s+\d{1,2}/\d{1,2}",
    r"DEBIT\s+CARD\s+(?:PURCHASE|PAYMENT)",
    r"CREDIT\s+CARD\s+PAYMENT",
    r"POS\s+(?:PURCHASE|DEBIT)",
    r"ZELLE\s+PAYMENT\s+(?:TO|FROM)",
    r"ZELLE\s+(?:TO|FROM)",
    r"ACH\s+(?:DEBIT|CREDIT)\s+(?:FROM|TO)",
    r"ACH\s+(?:DEBIT|CREDIT)",
    r"ELECTRONIC\s+(?:WITHDRAWAL|DEPOSIT)",
    r"ONLINE\s+(?:PMT|PAYMENT|TRANSFER)\s+(?:TO|FROM)?",
    r"BILL\s+PAYMENT",
    r"CHECKCARD\s+\d{1,4}",
    r"CHECKCARD",
    r"CHECK\s+CARD\s+PURCHASE",
    r"WEB\s+AUTHORIZED\s+PMT",
    r"RECURRING\s+(?:PAYMENT|DEBIT)",
    r"AUTO\s+PAY",
    r"WIRE\s+TRANSFER\s+(?:TO|FROM)?",
    r"DIRECT\s+DEPOSIT",
    r"DEPOSIT\s+FROM",
]
_PREFIX_RE = re.compile(
    r"^\s*(?:" + "|".join(_PREFIXES) + r")\b[:\s\-]*",
    re.IGNORECASE,
)

# Inline metadata fragments. We strip the keyword AND its value (until
# whitespace) so leftovers like "PPD ID:" do not stay behind.
_META_FRAGMENTS = [
    r"\bORIG\s+(?:CO\s+)?NAME[:#]\s*\S+",
    r"\bORIG\s+ID[:#]\s*\S+",
    r"\bCO\s+(?:ENTRY\s+DESCR|ID)[:#]\s*\S+",
    r"\bCO\s+ENTRY\s+DESCR[:#]?\s*\S+",
    r"\b(?:CCD|PPD|WEB|TEL|CTX|IAT|ARC)\s+ID[:#]?\s*\S+",
    r"\b(?:CCD|PPD|WEB|TEL|CTX|IAT|ARC)\b",
    r"\bID[:#]\s*\S+",
    r"\bIID[:#]?\s*\S+",
    r"\bINFO[:#]?\s*\S+",
    r"\bREF\s*#?\s*\S+",
    r"\bF[:#]\d+",
    r"\b\d{2}/\d{2}(?:/\d{2,4})?\b",  # inline dates
    r"\b\d{2}-\d{2}-\d{2,4}\b",
    r"#\s*\d+",
]
_META_RE = re.compile("|".join(_META_FRAGMENTS), re.IGNORECASE)

# Long alphanumeric tokens (10+ chars, must contain a digit) — bank reference IDs.
_LONG_ID_RE = re.compile(r"\b(?=[A-Z0-9]{10,}\b)(?=[A-Z0-9]*\d)[A-Z0-9]+\b")

# Trailing transaction codes like " 03/27" or " 24" left after stripping.
_TRAILING_NUM_RE = re.compile(r"\s+\d{1,4}\s*$")

_MULTISPACE_RE = re.compile(r"\s+")
_LEADING_PUNCT_RE = re.compile(r"^[\s:\-#*]+")
_TRAILING_PUNCT_RE = re.compile(r"[\s:\-#*]+$")

# Acronyms that should NOT be Title-cased.
_ACRONYMS = {
    "IRS", "USPS", "ATM", "POS", "CD", "DD", "USA", "USD", "DMV", "NYC",
    "LLC", "INC", "CO", "AT&T", "AMEX", "PNC", "BMO", "TD", "FCU", "DBA",
    "NSF", "ACH", "EFT", "PIN", "ID", "TV", "AC", "DC", "SF", "LA",
    "EU", "UK", "VA", "MA", "PA", "NJ", "CA", "TX", "FL", "IL", "OH",
}

# Words that should keep their natural casing if Title would butcher them.
_LOWERCASE_WORDS = {"and", "of", "the", "for", "to", "in", "at", "by", "on", "or"}


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


# Generic single words Plaid occasionally serves as ``merchant_name`` for
# transactions it couldn't actually enrich (e.g. "Online", "Mobile",
# "Payment" for a Bank of America credit-card autopay). These leak through
# the lowercase check in ``_looks_pretty`` and produce displays like just
# "Online" — less informative than cleaning the raw bank string would be.
# Comparison is case-insensitive against the *normalized* (lowercased,
# whitespace-collapsed) name so "online", "Online ", "ONLINE" all match.
_GENERIC_MERCHANT_NAMES = frozenset({
    "online",
    "mobile",
    "payment",
    "recurring",
    "transfer",
    "withdrawal",
    "deposit",
    "purchase",
    "debit",
    "credit",
    "online payment",
    "online transfer",
    "mobile payment",
    "mobile recurring",
    "online mobile",
    "bill payment",
    "auto pay",
    "direct deposit",
    "ach payment",
    "ach transfer",
    "web payment",
})


def _looks_pretty(value: str) -> bool:
    """Heuristic: a string is "pretty" if it has lowercase letters or is short
    and clean. Plaid's `merchant_name` and counterparty `name` are pretty.

    Generic single-word merchant names ("Online", "Mobile", ...) are
    rejected so the cleanup pipeline falls through to the raw bank string
    — "ONLINE/MOBILE RECURRING" → "Online/mobile Recurring" beats just
    "Online" in every UI surface that renders a transaction.
    """
    if not value:
        return False
    normalized = " ".join(value.lower().split())
    if normalized in _GENERIC_MERCHANT_NAMES:
        return False
    if any(c.islower() for c in value):
        return True
    return len(value) <= 24 and not any(c.isdigit() for c in value)


def _from_counterparties(counterparties: Iterable[Mapping[str, Any]]) -> Optional[str]:
    if not counterparties:
        return None
    try:
        items: List[Mapping[str, Any]] = [c for c in counterparties if isinstance(c, Mapping)]
    except TypeError:
        return None
    if not items:
        return None
    merchants = [c for c in items if (c.get("type") or "").lower() == "merchant"]
    pool = merchants or items
    pool_sorted = sorted(
        pool,
        key=lambda c: _CONFIDENCE_RANK.get(c.get("confidence_level"), 0),
        reverse=True,
    )
    for c in pool_sorted:
        name = _coerce_str(c.get("name"))
        if name:
            return name
    return None


def _hostname_from_website(website: str) -> Optional[str]:
    if not website:
        return None
    raw = website.strip().lower()
    raw = re.sub(r"^https?://", "", raw)
    raw = raw.split("/", 1)[0]
    if raw.startswith("www."):
        raw = raw[4:]
    raw = raw.strip()
    if not raw or "." not in raw:
        return None
    label = raw.split(".")[0]
    if not label:
        return None
    return label[:1].upper() + label[1:]


def _smart_title(text: str) -> str:
    """Title-case while preserving acronyms and short connectors."""
    if not text:
        return text
    parts = text.split()
    out: List[str] = []
    for i, raw in enumerate(parts):
        token = raw.strip("()[]{}.,;:!?")
        suffix = raw[len(token):] if len(token) < len(raw) else ""
        prefix_len = len(raw) - len(raw.lstrip("()[]{}.,;:!?"))
        prefix = raw[:prefix_len]
        upper = token.upper()
        if upper in _ACRONYMS:
            rendered = upper
        elif token.isdigit():
            rendered = token
        elif i > 0 and token.lower() in _LOWERCASE_WORDS:
            rendered = token.lower()
        else:
            rendered = token[:1].upper() + token[1:].lower() if token else ""
        out.append(f"{prefix}{rendered}{suffix}")
    return " ".join(out)


def _truncate(text: str, limit: int = _MAX_LEN) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rstrip(" -:,.")
    return f"{cut}\u2026"


def _clean_raw_name(raw: str) -> str:
    """Apply the heuristic ACH/POS cleanup pipeline to a raw bank string."""
    if not raw:
        return ""
    text = raw
    # Remove zero-width / control chars.
    text = "".join(ch for ch in text if ch.isprintable())
    # Strip leading bank-statement prefixes (may have several glued together).
    for _ in range(3):
        new = _PREFIX_RE.sub("", text)
        if new == text:
            break
        text = new
    text = _META_RE.sub(" ", text)
    text = _LONG_ID_RE.sub(" ", text)
    text = _MULTISPACE_RE.sub(" ", text).strip()
    text = _TRAILING_NUM_RE.sub("", text)
    text = _LEADING_PUNCT_RE.sub("", text)
    text = _TRAILING_PUNCT_RE.sub("", text)
    text = _MULTISPACE_RE.sub(" ", text).strip()
    if not text:
        return ""
    if not any(c.islower() for c in text):
        text = _smart_title(text)
    return text


def normalize_transaction_title(tx: Mapping[str, Any]) -> str:
    """
    Build a short, human-friendly display title for a transaction-like mapping.

    Accepts dicts whose shape mirrors the `transactions` table or a
    `RecurringStream` (uses `description` as the raw fallback).
    Never raises; always returns a non-empty string ("Transaction" as last resort).
    """
    if not isinstance(tx, Mapping):
        return "Transaction"

    merchant = _coerce_str(tx.get("merchant_name"))
    if merchant and _looks_pretty(merchant):
        return _truncate(merchant)

    cp_name = _from_counterparties(tx.get("counterparties") or [])
    if cp_name and _looks_pretty(cp_name):
        return _truncate(cp_name)

    site_name = _hostname_from_website(_coerce_str(tx.get("website")))
    if site_name:
        return _truncate(site_name)

    raw = _coerce_str(tx.get("name")) or _coerce_str(tx.get("description"))
    if merchant and not raw:
        return _truncate(_smart_title(merchant))
    cleaned = _clean_raw_name(raw)
    if cleaned:
        return _truncate(cleaned)
    if merchant:
        return _truncate(_smart_title(merchant))
    if raw:
        return _truncate(_smart_title(raw))
    return "Transaction"


__all__ = ["normalize_transaction_title"]
