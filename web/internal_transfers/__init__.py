"""Internal-transfer classification feature module.

Manages the family-wide list of counterparty names that flag Plaid
``TRANSFER_IN`` / ``TRANSFER_OUT`` transactions as internal (e.g. Zelle
between spouses). The classifier lives in ``web/plaid/internal_transfer.py``
because it runs inside the Plaid sync pipeline; this package owns the
configuration surface (DB read/write + REST endpoints).
"""
from .routes import router as internal_transfers_router

__all__ = ["internal_transfers_router"]
