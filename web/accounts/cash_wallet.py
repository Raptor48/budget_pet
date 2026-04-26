"""Designated per-user cash wallet account (no Plaid link).

A cash wallet is any active manual depository row with subtype "cash". Up
through 2026-04 there was only ever one per user, hard-coded to name
"Cash" — that's still the default that ``ensure_cash_wallet`` creates for
legacy callers, but ``POST /api/accounts/cash-wallet`` accepts a custom
name so users can keep, e.g., a "Travel envelope" alongside their main
"Cash" wallet. Identification no longer depends on the name.
"""

CASH_WALLET_NAME = "Cash"
CASH_WALLET_TYPE = "depository"
CASH_WALLET_SUBTYPE = "cash"


def is_designated_cash_wallet(row: dict) -> bool:
    """True if this account row is a manual cash wallet.

    Identification is shape-based now (no Plaid link, manual depository
    with cash subtype) so multiple custom-named wallets are supported.
    """
    if not row.get("is_active", True):
        return False
    if row.get("plaid_account_id") is not None:
        return False
    return (
        row.get("type") == CASH_WALLET_TYPE
        and (row.get("subtype") or "") == CASH_WALLET_SUBTYPE
    )
