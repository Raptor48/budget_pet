"""
Plaid integration constants (env-tunable).

PFC taxonomy version — see https://plaid.com/docs/transactions/pfc-migration/
Transactions history window — see https://plaid.com/docs/api/link/#link-token-create-request-transactions-days-requested
"""
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

DEFAULT_PLAID_PFC_CATEGORY_VERSION = "v2"

# Plaid allows up to 730 days (~24 months) of transaction history via
# transactions.days_requested. The subscription fee model (billed per-Item per
# month) does not change with this value, so we request the maximum by default.
DEFAULT_PLAID_TRANSACTIONS_DAYS_REQUESTED = 730
MAX_PLAID_TRANSACTIONS_DAYS_REQUESTED = 730
MIN_PLAID_TRANSACTIONS_DAYS_REQUESTED = 1


def get_plaid_pfc_category_version() -> str:
    """Return 'v1' or 'v2' for transactions/sync and transactions/recurring/get options."""
    raw = os.getenv("PLAID_PERSONAL_FINANCE_CATEGORY_VERSION", DEFAULT_PLAID_PFC_CATEGORY_VERSION)
    v = (raw or DEFAULT_PLAID_PFC_CATEGORY_VERSION).lower().strip()
    if v not in ("v1", "v2"):
        return DEFAULT_PLAID_PFC_CATEGORY_VERSION
    return v


def get_plaid_transactions_days_requested() -> int:
    """
    Return the number of days of historical transactions to request when creating
    a Plaid Link token. Clamped to the valid Plaid range [1..730]. Invalid values
    fall back to the default.
    """
    raw = os.getenv("PLAID_TRANSACTIONS_DAYS_REQUESTED")
    if raw is None or not raw.strip():
        return DEFAULT_PLAID_TRANSACTIONS_DAYS_REQUESTED
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        logger.warning(
            "Invalid PLAID_TRANSACTIONS_DAYS_REQUESTED=%r; falling back to %d",
            raw,
            DEFAULT_PLAID_TRANSACTIONS_DAYS_REQUESTED,
        )
        return DEFAULT_PLAID_TRANSACTIONS_DAYS_REQUESTED
    if value < MIN_PLAID_TRANSACTIONS_DAYS_REQUESTED:
        return MIN_PLAID_TRANSACTIONS_DAYS_REQUESTED
    if value > MAX_PLAID_TRANSACTIONS_DAYS_REQUESTED:
        return MAX_PLAID_TRANSACTIONS_DAYS_REQUESTED
    return value


def get_balance_min_last_updated_datetime() -> datetime:
    """
    Oldest acceptable balance timestamp for Plaid requests that support
    ``min_last_updated_datetime`` (``/accounts/balance/get`` and, for some
    institutions, ``/transactions/sync`` balance refresh).

    Capital One (``ins_128026``) requires this for non-depository accounts; for
    other institutions Plaid ignores it. Use the maximum supported history
    window (730 days) so the floor stays permissive and avoids
    ``LAST_UPDATED_DATETIME_OUT_OF_RANGE`` when the link requests fewer txn days.
    """
    return datetime.now(timezone.utc) - timedelta(days=MAX_PLAID_TRANSACTIONS_DAYS_REQUESTED)
