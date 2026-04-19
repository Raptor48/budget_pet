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
    """Every income / expense aggregate must filter out flagged transfers.

    The ``_not_internal_transfer`` helper in ``web/reports/repo.py`` is the
    single source of truth; these tests assert the resulting SQL carries
    the predicate for the endpoints users hit most often.
    """

    @pytest.mark.asyncio
    async def test_cash_flow_excludes_internal_transfers(self):
        repo = ReportsRepository()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"income_cents": 0, "expenses_cents": 0}
        )
        pool = make_mock_pool(conn)
        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_cash_flow("2026-04")

        sqls = [call.args[0] for call in conn.fetchrow.call_args_list]
        assert sqls, "cash-flow must hit the DB"
        for sql in sqls:
            assert "is_internal_transfer" in sql

    @pytest.mark.asyncio
    async def test_by_category_excludes_internal_transfers(self):
        repo = ReportsRepository()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        pool = make_mock_pool(conn)
        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_by_category("2026-04")

        sqls = [call.args[0] for call in conn.fetch.call_args_list]
        assert sqls, "by-category must hit the DB"
        for sql in sqls:
            assert "is_internal_transfer" in sql

    @pytest.mark.asyncio
    async def test_income_breakdown_excludes_internal_transfers(self):
        repo = ReportsRepository()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        pool = make_mock_pool(conn)
        with patch("web.reports.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.get_income_breakdown("2026-04")

        sqls = [call.args[0] for call in conn.fetch.call_args_list]
        assert sqls, "income-breakdown must hit the DB"
        for sql in sqls:
            assert "is_internal_transfer" in sql
