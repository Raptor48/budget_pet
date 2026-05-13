"""Reports exclude plaid_sandbox unless REPORTS_INCLUDE_PLAID_SANDBOX is set.

Patches go to ``web.finance.predicates.reports_include_plaid_sandbox`` —
that's where ``_sandbox_tx_filter`` (and every other module routed through
the canonical predicates helper in :mod:`web.finance.predicates`) reads
the runtime toggle. Patching the re-export at ``web.reports.repo`` would
no-op now that the helper lives in a single source of truth.
"""
from unittest.mock import patch

from web.reports.repo import _sandbox_tx_filter, _sandbox_tx_filter_no_alias


def test_sandbox_filter_active_by_default():
    with patch(
        "web.finance.predicates.reports_include_plaid_sandbox",
        return_value=False,
    ):
        assert "plaid_sandbox" in _sandbox_tx_filter("t")
        assert "t." in _sandbox_tx_filter("t")
        assert "plaid_sandbox" in _sandbox_tx_filter_no_alias()


def test_sandbox_filter_disabled_when_env_include():
    with patch(
        "web.finance.predicates.reports_include_plaid_sandbox",
        return_value=True,
    ):
        assert _sandbox_tx_filter("t") == ""
        assert _sandbox_tx_filter_no_alias() == ""
