"""Designated per-user cash wallet account (no Plaid link)."""

CASH_WALLET_NAME = "Cash"
CASH_WALLET_TYPE = "depository"
CASH_WALLET_SUBTYPE = "cash"


def is_designated_cash_wallet(row: dict) -> bool:
    """True if this account row is the system cash wallet for manual cash transactions."""
    if not row.get("is_active", True):
        return False
    if row.get("plaid_account_id") is not None:
        return False
    return (
        row.get("name") == CASH_WALLET_NAME
        and row.get("type") == CASH_WALLET_TYPE
        and (row.get("subtype") or "") == CASH_WALLET_SUBTYPE
    )
