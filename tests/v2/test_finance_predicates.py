"""
Unit tests for :mod:`web.finance.predicates` — the single source of truth
for transaction-class / privacy / sandbox SQL fragments shared by reports,
budgets, transactions list, and the bot leaderboard.

These shapes are pinned by API contract: every aggregator interpolates
them into ``f"…"`` SQL strings, so a one-character change here ripples
into every read path. Lock the format down with explicit assertions.
"""
from __future__ import annotations

from unittest.mock import patch

from web.finance.predicates import (
    expense_predicate,
    income_predicate,
    internal_transfer_predicate,
    not_internal_transfer_predicate,
    private_visibility_filter,
    sandbox_exclusion_filter,
)


class TestClassPredicates:
    def test_default_alias_uses_t(self):
        assert income_predicate() == "t.transaction_class = 'income'"
        assert expense_predicate() == "t.transaction_class = 'expense'"
        assert (
            internal_transfer_predicate()
            == "t.transaction_class = 'internal_transfer'"
        )
        assert (
            not_internal_transfer_predicate()
            == "t.transaction_class <> 'internal_transfer'"
        )

    def test_empty_alias_drops_qualifier(self):
        assert income_predicate("") == "transaction_class = 'income'"
        assert expense_predicate("") == "transaction_class = 'expense'"
        assert internal_transfer_predicate("") == "transaction_class = 'internal_transfer'"

    def test_custom_alias(self):
        assert income_predicate("tx") == "tx.transaction_class = 'income'"


class TestPrivateVisibilityFilter:
    def test_emits_leading_and(self):
        """The fragment is concatenated into a WHERE clause that already
        ended with another predicate. Must lead with `` AND `` so the
        callsite stays grammatical without extra glue."""
        sql = private_visibility_filter("t", 2)
        assert sql.startswith(" AND (")

    def test_subselect_uses_independent_alias(self):
        """The privacy EXISTS uses a unique inner alias (``_pa``) so it
        never collides with the outer query's accounts alias."""
        sql = private_visibility_filter("t", 2)
        assert "FROM accounts _pa" in sql
        assert "_pa.id = t.account_id" in sql
        assert "_pa.user_id = $2" in sql

    def test_alias_propagates(self):
        sql = private_visibility_filter("tx", 5)
        assert "NOT tx.is_private" in sql
        assert "_pa.id = tx.account_id" in sql
        assert "_pa.user_id = $5" in sql


class TestSandboxExclusionFilter:
    def test_returns_empty_when_sandbox_include(self):
        with patch(
            "web.finance.predicates.reports_include_plaid_sandbox",
            return_value=True,
        ):
            assert sandbox_exclusion_filter() == ""
            assert sandbox_exclusion_filter("") == ""
            assert sandbox_exclusion_filter("tx") == ""

    def test_returns_exclusion_clause_when_sandbox_excluded(self):
        with patch(
            "web.finance.predicates.reports_include_plaid_sandbox",
            return_value=False,
        ):
            sql = sandbox_exclusion_filter("t")
            assert sql.startswith(" AND (")
            assert "t.source IS NULL" in sql
            assert "t.source <> 'plaid_sandbox'" in sql

    def test_no_alias_form(self):
        with patch(
            "web.finance.predicates.reports_include_plaid_sandbox",
            return_value=False,
        ):
            sql = sandbox_exclusion_filter("")
            # No "t." prefix when alias is empty — used by `FROM transactions`
            # without a qualifier.
            assert "source IS NULL" in sql
            assert "t.source" not in sql


class TestReportsRepoReexports:
    """The legacy underscore-prefixed names in ``web.reports.repo`` must
    keep behaving exactly like their canonical counterparts so any callsite
    or test importing them by name still works."""

    def test_reports_repo_helpers_match_canonical(self):
        from web.reports.repo import (
            _expense_predicate,
            _income_predicate,
            _internal_transfer_predicate,
            _not_internal_transfer,
            _private_tx_filter_with_idx,
            _sandbox_tx_filter,
        )

        assert _income_predicate("t") == income_predicate("t")
        assert _expense_predicate("t") == expense_predicate("t")
        assert _internal_transfer_predicate("t") == internal_transfer_predicate("t")
        assert _not_internal_transfer("t") == not_internal_transfer_predicate("t")
        assert _private_tx_filter_with_idx("t", 2) == private_visibility_filter("t", 2)

        with patch(
            "web.finance.predicates.reports_include_plaid_sandbox",
            return_value=False,
        ):
            assert _sandbox_tx_filter("t") == sandbox_exclusion_filter("t")
