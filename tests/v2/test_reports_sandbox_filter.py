"""Reports exclude plaid_sandbox unless REPORTS_INCLUDE_PLAID_SANDBOX is set."""
from unittest.mock import patch

from web.reports.repo import _sandbox_tx_filter, _sandbox_tx_filter_no_alias


def test_sandbox_filter_active_by_default():
    with patch("web.reports.repo.reports_include_plaid_sandbox", return_value=False):
        assert "plaid_sandbox" in _sandbox_tx_filter("t")
        assert "t." in _sandbox_tx_filter("t")
        assert "plaid_sandbox" in _sandbox_tx_filter_no_alias()


def test_sandbox_filter_disabled_when_env_include():
    with patch("web.reports.repo.reports_include_plaid_sandbox", return_value=True):
        assert _sandbox_tx_filter("t") == ""
        assert _sandbox_tx_filter_no_alias() == ""
