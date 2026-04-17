"""Centralized environment toggles (read-only at import time per call)."""
import os


def reports_include_plaid_sandbox() -> bool:
    """
    When true, reports, budget progress, and CSV export include `source=plaid_sandbox` rows.

    Priority:
    - ``REPORTS_INCLUDE_PLAID_SANDBOX=false|0|no|off`` → always exclude (even in sandbox).
    - ``REPORTS_INCLUDE_PLAID_SANDBOX=true|1|yes|on`` → always include.
    - If unset: **include** when ``PLAID_ENV=sandbox`` so local/dashboard data matches linked
      sandbox banks; otherwise exclude (production / development Plaid).
    """
    raw = os.getenv("REPORTS_INCLUDE_PLAID_SANDBOX", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return os.getenv("PLAID_ENV", "").strip().lower() == "sandbox"
