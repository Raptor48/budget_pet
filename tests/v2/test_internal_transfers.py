"""
Unit tests for the intra-family internal-transfer classifier and its
integration points.

Covered:
    * ``normalize_name`` — strips bank boilerplate and is case-insensitive.
    * ``classify_internal_transfer`` — matches Plaid TRANSFER_IN/OUT rows
      against the family-wide names list across merchant_name, name and
      counterparties[].
    * ``TransactionsRepository.update_transaction`` — flips
      ``is_internal_transfer_manual`` whenever the user patches the
      ``is_internal_transfer`` flag, so auto re-scans never overwrite an
      explicit user choice.
    * ``ReportsRepository`` queries — every income / expense aggregate
      includes a ``NOT ... is_internal_transfer`` predicate so flagged
      transfers drop out of totals.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.plaid.internal_transfer import (
    classify_internal_transfer,
    match_family_account_transfers,
    normalize_name,
    normalize_names,
)
from web.reports.repo import ReportsRepository
from web.transactions.repo import TransactionsRepository


# ---------------------------------------------------------------------------
# normalize_name / normalize_names
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_uppercases_and_trims(self):
        assert normalize_name("  John Doe  ") == "JOHN DOE"

    def test_strips_zelle_payment_from_wrapper(self):
        assert (
            normalize_name("Zelle payment from ANASTASIIA STOLPOVSKAIA")
            == "ANASTASIIA STOLPOVSKAIA"
        )

    def test_strips_zelle_payment_to_wrapper(self):
        assert (
            normalize_name("Zelle Payment To DENIS STOLPOVSKII")
            == "DENIS STOLPOVSKII"
        )

    def test_strips_ach_wire_wrappers(self):
        assert normalize_name("ACH TRANSFER JOHN SMITH") == "JOHN SMITH"
        assert normalize_name("Wire credit MARY JONES") == "MARY JONES"

    def test_collapses_internal_whitespace(self):
        assert normalize_name("John    Doe\tSmith") == "JOHN DOE SMITH"

    def test_empty_input_returns_empty_string(self):
        assert normalize_name(None) == ""
        assert normalize_name("") == ""
        assert normalize_name("   ") == ""

    def test_normalize_names_dedupes_case_insensitively(self):
        out = normalize_names(
            ["Anastasiia Stolpovskaia", "ANASTASIIA STOLPOVSKAIA", "  denis  "]
        )
        assert out == ["ANASTASIIA STOLPOVSKAIA", "DENIS"]

    def test_normalize_names_skips_empty(self):
        assert normalize_names(["", None, "  ", "Alice"]) == ["ALICE"]


# ---------------------------------------------------------------------------
# classify_internal_transfer
# ---------------------------------------------------------------------------


class TestClassifyInternalTransfer:
    def test_matches_zelle_from_spouse_on_transfer_in(self):
        assert classify_internal_transfer(
            pfc_primary="TRANSFER_IN",
            merchant_name=None,
            name="Zelle payment from ANASTASIIA STOLPOVSKAIA",
            counterparties=None,
            normalized_names=["ANASTASIIA STOLPOVSKAIA"],
        )

    def test_matches_zelle_to_spouse_on_transfer_out(self):
        assert classify_internal_transfer(
            pfc_primary="TRANSFER_OUT",
            merchant_name=None,
            name="Zelle payment to DENIS STOLPOVSKII",
            counterparties=None,
            normalized_names=["DENIS STOLPOVSKII"],
        )

    def test_matches_via_counterparties_name(self):
        """Some banks surface the spouse's name only in counterparties[]."""
        assert classify_internal_transfer(
            pfc_primary="TRANSFER_IN",
            merchant_name="ZELLE",
            name="ZELLE CREDIT",
            counterparties=[{"name": "Anastasiia Stolpovskaia", "type": "person"}],
            normalized_names=["ANASTASIIA STOLPOVSKAIA"],
        )

    def test_does_not_match_purchase_at_similarly_named_merchant(self):
        """PFC gate: if it's not a transfer, a name match is ignored."""
        assert not classify_internal_transfer(
            pfc_primary="FOOD_AND_DRINK",
            merchant_name="STOLPOVSKII BAKERY",
            name="STOLPOVSKII BAKERY #42",
            counterparties=None,
            normalized_names=["DENIS STOLPOVSKII"],
        )

    def test_empty_name_list_disables_matching(self):
        """If the family hasn't configured names yet, classify is a no-op."""
        assert not classify_internal_transfer(
            pfc_primary="TRANSFER_IN",
            merchant_name=None,
            name="Zelle payment from ANASTASIIA",
            counterparties=None,
            normalized_names=[],
        )

    def test_counterparties_string_json_is_tolerated(self):
        """Plaid's JSONB sometimes reaches us as a serialized string."""
        assert classify_internal_transfer(
            pfc_primary="TRANSFER_IN",
            merchant_name=None,
            name=None,
            counterparties='[{"name": "Denis Stolpovskii", "type": "person"}]',
            normalized_names=["DENIS STOLPOVSKII"],
        )

    def test_unrelated_transfer_not_flagged(self):
        assert not classify_internal_transfer(
            pfc_primary="TRANSFER_OUT",
            merchant_name="CHASE CREDIT CARD PAYMENT",
            name="Online Transfer to credit card ending 1234",
            counterparties=None,
            normalized_names=["ANASTASIIA STOLPOVSKAIA"],
        )


# ---------------------------------------------------------------------------
# update_transaction: manual-override protection
# ---------------------------------------------------------------------------


class TestManualInternalTransferOverride:
    """Patching ``is_internal_transfer`` must also set ``_manual=TRUE`` so the
    classifier's re-scan never clobbers an explicit user decision."""

    @pytest.fixture
    def repo(self):
        return TransactionsRepository()

    @pytest.mark.asyncio
    async def test_patch_sets_manual_sentinel_and_writes_both_columns(self, repo):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 77,
                "is_internal_transfer": True,
                "is_internal_transfer_manual": True,
                "amount_cents": -5000,
            }
        )
        pool = make_mock_pool(conn)
        with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
            result = await repo.update_transaction(77, {"is_internal_transfer": True})

        sql_used = conn.fetchrow.call_args[0][0]
        assert "is_internal_transfer" in sql_used
        assert "is_internal_transfer_manual" in sql_used, (
            "manual sentinel must be written alongside the user flag"
        )

        args = conn.fetchrow.call_args[0]
        # Positional args after the SQL: (id, <column values in dict order>)
        assert args[1] == 77
        # The repo appends `is_internal_transfer_manual=True` when the user
        # patches is_internal_transfer — both values should be present.
        values = list(args[2:])
        assert True in values  # is_internal_transfer
        assert values.count(True) >= 2  # is_internal_transfer + manual flag
        assert result is not None

    @pytest.mark.asyncio
    async def test_unrelated_patch_does_not_touch_manual_flag(self, repo):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"id": 78, "user_note": "lunch", "amount_cents": 1500}
        )
        pool = make_mock_pool(conn)
        with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.update_transaction(78, {"user_note": "lunch"})

        sql_used = conn.fetchrow.call_args[0][0]
        assert "user_note" in sql_used
        assert "is_internal_transfer_manual" not in sql_used, (
            "only explicit is_internal_transfer patches should touch the manual flag"
        )


# ---------------------------------------------------------------------------
# Reports SQL exclusion predicate
# ---------------------------------------------------------------------------


class TestReportsExcludeInternalTransfers:
    """Every income / expense aggregate must filter out internal transfers.

    Post-V2 the single source of truth is the ``transaction_class`` column
    materialized by ``web.classification.classifier``. Income aggregates
    select ``transaction_class = 'income'``, expense aggregates select
    ``transaction_class = 'expense'`` — so internal transfers are excluded
    by construction, not by a separate ``NOT is_internal_transfer`` clause.
    These tests pin that contract at the SQL boundary.
    """

    @pytest.mark.asyncio
    async def test_cash_flow_uses_class_buckets(self):
        repo = ReportsRepository()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "income_cents": 0,
                "expenses_cents": 0,
                "internal_transfer_cents": 0,
            }
        )
        pool = make_mock_pool(conn)
        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_cash_flow("2026-04")

        sqls = [call.args[0] for call in conn.fetchrow.call_args_list]
        assert sqls, "cash-flow must hit the DB"
        for sql in sqls:
            # All three buckets must be computed in the same query so the
            # cash-flow identity (income + expense + internal ≡ SUM(amount))
            # is a single DB round-trip.
            assert "transaction_class = 'income'" in sql
            assert "transaction_class = 'expense'" in sql
            assert "transaction_class = 'internal_transfer'" in sql

    @pytest.mark.asyncio
    async def test_by_category_uses_expense_class(self):
        repo = ReportsRepository()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        pool = make_mock_pool(conn)
        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_by_category("2026-04")

        sqls = [call.args[0] for call in conn.fetch.call_args_list]
        assert sqls, "by-category must hit the DB"
        for sql in sqls:
            assert "transaction_class = 'expense'" in sql
            # Refund-correct: no amount-sign filter that would drop negatives.
            assert "amount_cents > 0" not in sql

    @pytest.mark.asyncio
    async def test_income_breakdown_uses_income_class(self):
        repo = ReportsRepository()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        pool = make_mock_pool(conn)
        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_income_breakdown("2026-04")

        sqls = [call.args[0] for call in conn.fetch.call_args_list]
        assert sqls, "income-breakdown must hit the DB"
        for sql in sqls:
            assert "transaction_class = 'income'" in sql


# ---------------------------------------------------------------------------
# match_family_account_transfers: SQL contract
# ---------------------------------------------------------------------------


class TestMatchFamilyAccountTransfers:
    """The pair-matcher is one SQL statement; behavioural assertions (same-user
    match, off-by-1-cent miss, 4-day miss, manual-override protection, 2x2
    greedy pairing) live in the SQL itself and would require a live
    Postgres to verify end-to-end. These tests pin the SQL contract — the
    predicates, join shape, dedup strategy, and manual-flag guard — so
    regressions that silently weaken the classifier fail loudly here.

    The behavioural matrix documented in the plan:
        * self->self match (two accounts owned by the same user)
        * cross-user match (Denis -> Anastasiia)
        * unknown owner_uid on either side -> no pair
        * amount mismatch by 1 cent -> no pair
        * date gap > 3 days -> no pair
        * is_internal_transfer_manual=TRUE -> never touched
        * 2x2 greedy pairing (ROW_NUMBER deduplication)

    is enforced by the SQL predicates asserted below.
    """

    @pytest.mark.asyncio
    async def test_sql_contains_pair_matching_rules(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        pool = make_mock_pool(conn)
        with patch("web.plaid.internal_transfer.asyncpg"):
            pass

        # Call directly with the mock connection rather than a pool since the
        # matcher is designed to run inside an existing connection (used
        # by both import_transactions and the rescan route).
        await match_family_account_transfers(conn, horizon_days=30)

        assert conn.fetch.await_count == 1, "matcher runs exactly one SQL statement"
        sql = conn.fetch.call_args[0][0]
        args = conn.fetch.call_args[0][1:]

        # horizon is passed as a positional placeholder, not inlined.
        assert args == (30,)

        # PFC gate: only TRANSFER_IN/OUT are considered.
        assert "TRANSFER_IN" in sql and "TRANSFER_OUT" in sql

        # Amount must match exactly to the cent (opposite signs).
        assert "i.amount_cents = -o.amount_cents" in sql
        assert "o.amount_cents > 0" in sql

        # Date window +/- 3 days.
        assert "ABS(o.date - i.date) <= 3" in sql

        # Different accounts (otherwise a single row would self-match).
        assert "i.account_id <> o.account_id" in sql

        # Both sides need a resolvable owner; the matcher falls back from
        # accounts.user_id to plaid_items.user_id.
        assert "COALESCE(a.user_id, p.user_id)" in sql
        assert "i.owner_uid IS NOT NULL" in sql
        assert "o.owner_uid IS NOT NULL" in sql

        # Manual overrides stay put on both the candidate filter and the
        # final UPDATE WHERE clause.
        assert "is_internal_transfer_manual = FALSE" in sql

        # Only Plaid-sourced rows participate (cash transfers have no
        # matching counterparty anyway).
        assert "'plaid'" in sql and "'plaid_sandbox'" in sql

        # Greedy pairing uses ROW_NUMBER on both sides so each txn pairs
        # with at most one counterpart.
        assert "ROW_NUMBER()" in sql
        assert "rn_out = 1" in sql and "rn_in = 1" in sql

        # The UPDATE only flips rows that are currently FALSE and not
        # manually overridden.
        assert "is_internal_transfer = TRUE" in sql
        assert "RETURNING id" in sql

    @pytest.mark.asyncio
    async def test_returns_updated_row_count(self):
        """The function reports how many rows flipped to TRUE — the value the
        UI surfaces as ``pair_rows_updated``."""
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[{"id": 11}, {"id": 12}, {"id": 13}, {"id": 14}]
        )
        count = await match_family_account_transfers(conn, horizon_days=90)
        assert count == 4

    @pytest.mark.asyncio
    async def test_none_horizon_means_full_history(self):
        """horizon_days=None must pass NULL through so the SQL scans everything."""
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        await match_family_account_transfers(conn, horizon_days=None)
        assert conn.fetch.await_count == 1
        assert conn.fetch.call_args[0][1] is None

    @pytest.mark.asyncio
    async def test_non_positive_horizon_short_circuits(self):
        """Negative/zero horizons are a programming error upstream; we return
        0 without touching the DB rather than corrupt the predicate."""
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        assert await match_family_account_transfers(conn, horizon_days=0) == 0
        assert await match_family_account_transfers(conn, horizon_days=-5) == 0
        assert conn.fetch.await_count == 0
