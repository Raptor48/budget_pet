"""Hand-curated brand → domain mapping for the long tail of transactions
where ``merchant_name`` is NULL but ``display_title`` carries a usable
service name (Zelle, Chase Bank, Wells Fargo, ...).

Why curate by hand:

Brandfetch search is unreliable for top-volume services. Empirical
2026-05 spot-checks against our production DB:

* "Zelle" → top hit ``myzeller.com`` qS 0.99 (POS terminal company,
  not Zelle Pay). Right hit ``zellepay.com`` is #2 at qS 0.92 —
  loses on quality despite being the correct brand.
* "Chase Bank" → top hit ``chasebank.com`` qS 0.15 (below our 0.5
  threshold, so we'd skip). Correct hit ``chase.com`` requires the
  shorter query "Chase".

A single Zelle row mismatch is multiplied by the row count for that
display_title — Zelle alone has ~500 transactions in the dataset, so
one bad search result paints 500 wrong logos. The curation cost
(adding ~30 entries by hand) is much lower than the user-visible
quality cost of getting it wrong.

How the pipeline uses this:

1. :func:`lookup_known_service` is called *before* Brandfetch search.
   When the normalized key matches, the orchestrator skips search
   entirely and goes straight to ``get_brand(domain)`` for the
   correct assets.
2. :func:`is_bank_noise` is called to short-circuit display_titles
   that are not brands at all — "Payment from Maria", "Wire Fee",
   "Cash Redemption". These should not be enriched at any tier.
"""

from __future__ import annotations

import re
from typing import Optional


# Lowercased + whitespace-collapsed display_title → canonical domain.
# Add entries when a top-N missing-logo merchant emerges from prod
# data; do not add speculative entries (the whole point of curation
# is that every entry was verified by a human against the real brand).
KNOWN_SERVICES: dict[str, str] = {
    # ── Person-to-person + digital wallets ──
    "zelle": "zellepay.com",
    "venmo": "venmo.com",
    "cash app": "cash.app",
    "paypal": "paypal.com",
    "apple pay": "apple.com",
    "google pay": "google.com",
    "stripe": "stripe.com",
    # ── US banks (display_title leaks across multiple syntaxes) ──
    "chase": "chase.com",
    "chase bank": "chase.com",
    "wells fargo": "wellsfargo.com",
    "bank of america": "bankofamerica.com",
    # BoA's autopay debit lands as "BA ELECTRONIC PAYMENT" → "Ba Electronic Payment".
    "ba electronic payment": "bankofamerica.com",
    "capital one": "capitalone.com",
    "citi": "citi.com",
    "citibank": "citi.com",
    "us bank": "usbank.com",
    "usaa": "usaa.com",
    "ally bank": "ally.com",
    "ally": "ally.com",
    "discover": "discover.com",
    "american express": "americanexpress.com",
    "amex": "americanexpress.com",
    # ── Delivery, transport, commerce ──
    "amazon": "amazon.com",
    "doordash": "doordash.com",
    "uber": "uber.com",
    "uber eats": "ubereats.com",
    "lyft": "lyft.com",
    "instacart": "instacart.com",
    # ── Subscriptions ──
    "netflix": "netflix.com",
    "spotify": "spotify.com",
    "youtube premium": "youtube.com",
    "youtube": "youtube.com",
    "apple": "apple.com",
    "apple.com/bill": "apple.com",
    # ── Utilities / gov ──
    "irs": "irs.gov",
    "usps": "usps.com",
    "con edison": "coned.com",
    "verizon": "verizon.com",
    "att": "att.com",
    "t-mobile": "t-mobile.com",
    "tmobile": "t-mobile.com",
    # ── Finance / investing ──
    "robinhood": "robinhood.com",
    "fidelity": "fidelity.com",
    "vanguard": "vanguard.com",
    "schwab": "schwab.com",
    "charles schwab": "schwab.com",
    "coinbase": "coinbase.com",
    "binance": "binance.com",
    # ── Common merchants we kept seeing in scoping ──
    "affirm": "affirm.com",
    "best egg": "bestegg.com",
    "rover": "rover.com",
}


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace. Matches the same shape used by
    the migration that purges generic merchant entries, so a key
    curated here matches a display_title regardless of casing or
    trailing-whitespace drift from the title-case pipeline."""
    if not text:
        return ""
    return " ".join(text.strip().lower().split())


def lookup_known_service(text: str) -> Optional[str]:
    """Return the curated domain for ``text``, or None when not in the map.

    Match is case-insensitive and whitespace-tolerant. Returns the
    canonical domain string (e.g. ``"zellepay.com"``) suitable for
    passing directly to :func:`web.enrichment.brandfetch.get_brand`.
    """
    return KNOWN_SERVICES.get(_normalize(text))


# Patterns that disqualify a display_title from enrichment entirely.
# These are *not* brands — they're bank descriptors, transfer noise,
# or person-to-person payment lines. Searching Brandfetch for any of
# these returns either nothing useful or, worse, a confidently-wrong
# brand. Centralised here so both `names_to_enrich` (skip during
# enrichment) and the read-time JOIN (skip cached false hits) share
# the same definition.
#
# Add patterns sparingly. Each entry is one regex; keep them anchored
# and specific. False negatives ("skipped a real brand") are better
# than false positives ("painted a wrong brand on a money-movement
# row") because the no-logo path falls back to our gradient avatar,
# which is visually fine.
_BANK_NOISE_PATTERNS: list[re.Pattern[str]] = [
    # P2P / interbank money movement — the trailing name/amount is a
    # person or external account, never a brand.
    re.compile(r"^payment\s+(from|to)\s+\S", re.IGNORECASE),
    re.compile(r"^money\s+transfer\s+(from|to)\s+\S", re.IGNORECASE),
    re.compile(r"^payroll\s+ach\s+\S", re.IGNORECASE),
    re.compile(r"^book\s+transfer", re.IGNORECASE),
    re.compile(r"^chips\s+credit", re.IGNORECASE),
    # ATM operations — these are physical events, not merchants.
    re.compile(r"\batm\s+(cash\s+)?(deposit|withdrawal)\b", re.IGNORECASE),
    re.compile(r"^cash\s+(deposit|withdrawal|redemption)", re.IGNORECASE),
    # Bank-internal fees and interest lines.
    re.compile(r"\bfee$", re.IGNORECASE),
    re.compile(r"^interest\s+(charged|earned|paid)", re.IGNORECASE),
    re.compile(r"^monthly\s+service", re.IGNORECASE),
    re.compile(r"\bwire\s+(fee|transfer)", re.IGNORECASE),
    re.compile(r"^(domestic|international)\s+(incoming|outgoing)\s+wire", re.IGNORECASE),
    # Account-mask references — the digits are an account number, not
    # a brand. Matches both ASCII "...1234" and Unicode bullet "••••1234".
    re.compile(r"\.{2,}\d{3,}\b"),
    re.compile(r"•{2,}\d{3,}\b"),
    re.compile(r"\bsav\s+\.\.\.\d", re.IGNORECASE),
    # Generic descriptors the cleanup pipeline sometimes lands on.
    re.compile(r"^thank\s+you", re.IGNORECASE),
    re.compile(r"\btransaction$", re.IGNORECASE),
    re.compile(r"^payment\s+thank\s+you", re.IGNORECASE),
]


def is_bank_noise(text: str) -> bool:
    """True when ``text`` should be skipped by every enrichment tier.

    Empty / whitespace-only inputs also return True so callers can
    pass display_title directly without a separate emptiness guard.
    """
    if not text or not text.strip():
        return True
    return any(p.search(text) for p in _BANK_NOISE_PATTERNS)
