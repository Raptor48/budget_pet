"""
Plaid integration constants (env-tunable).

PFC taxonomy version — see https://plaid.com/docs/transactions/pfc-migration/
"""
import os

DEFAULT_PLAID_PFC_CATEGORY_VERSION = "v2"


def get_plaid_pfc_category_version() -> str:
    """Return 'v1' or 'v2' for transactions/sync and transactions/recurring/get options."""
    raw = os.getenv("PLAID_PERSONAL_FINANCE_CATEGORY_VERSION", DEFAULT_PLAID_PFC_CATEGORY_VERSION)
    v = (raw or DEFAULT_PLAID_PFC_CATEGORY_VERSION).lower().strip()
    if v not in ("v1", "v2"):
        return DEFAULT_PLAID_PFC_CATEGORY_VERSION
    return v
