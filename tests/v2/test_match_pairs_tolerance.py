"""
Tests for the third (fee-tolerant) pass of ``web.classification.classifier.match_pairs``.

The first two passes are cent-exact; the third handles PayPal Instant
Transfer fees, small wire / FX rounding. Because ``match_pairs`` runs
SQL against a live Postgres we assert at the predicate level — the
queries should include the right WHERE clauses, exclude rows already
paired by the exact matchers, and use a tighter date window than the
cent-exact path.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from web.classification.classifier import match_pairs


@pytest.mark.asyncio
class TestMatchPairsToleranceSql:
    """Assert the SQL contract of the new tolerance query."""

    @staticmethod
    async def _run(conn: AsyncMock, horizon_days: int | None = 90) -> None:
        """Invoke match_pairs with all three passes returning no rows."""
        conn.fetch = AsyncMock(return_value=[])
        await match_pairs(conn, horizon_days=horizon_days)

    async def test_runs_three_sql_passes(self):
        """match_pairs fires cash↔debt, depo↔depo exact, depo↔depo tolerant."""
        conn = AsyncMock()
        await self._run(conn)
        assert conn.fetch.await_count == 3

    async def test_tolerance_sql_uses_plus_minus_one_day_window(self):
        """Tolerant matcher must be TIGHTER than the cent-exact one (±1 vs ±3)
        so a fee-adjusted match never beats an unrelated same-amount pair."""
        conn = AsyncMock()
        await self._run(conn)
        tolerance_sql = conn.fetch.await_args_list[2].args[0]
        assert "ABS(o.date - i.date) <= 1" in tolerance_sql
        assert "ABS(o.date - i.date) <= 3" not in tolerance_sql

    async def test_tolerance_sql_uses_greatest_500_or_1pct(self):
        """Tolerance formula: max(500¢ floor, 1% of outflow).

        The floor lets sub-$500 transfers absorb a flat $5 fee (PayPal
        Instant Transfer delta is usually <$5); the 1% ramp keeps large
        transfers from false-pairing against unrelated rows."""
        conn = AsyncMock()
        await self._run(conn)
        tolerance_sql = conn.fetch.await_args_list[2].args[0]
        assert "GREATEST(500, o.amount_cents / 100)" in tolerance_sql
        # Strictly positive delta — cent-exact pairs are handled earlier.
        assert "ABS(o.amount_cents + i.amount_cents) > 0" in tolerance_sql

    async def test_tolerance_sql_restricts_to_depository_depository(self):
        """Fees mostly live on cash↔cash routing; credit/loan pairs still
        need cent-exact matching (card-bill amounts never float)."""
        conn = AsyncMock()
        await self._run(conn)
        tolerance_sql = conn.fetch.await_args_list[2].args[0]
        assert "o.account_type = 'depository'" in tolerance_sql
        assert "i.account_type = 'depository'" in tolerance_sql

    async def test_tolerance_sql_excludes_already_paired_rows(self):
        """Cent-exact matches always win: their ids are passed as an array
        parameter and filtered out of the tolerant candidate pool."""
        conn = AsyncMock()
        await self._run(conn)
        tolerance_sql = conn.fetch.await_args_list[2].args[0]
        assert "NOT (t.id = ANY($2::int[]))" in tolerance_sql

    async def test_tolerance_sql_keeps_manual_override_guard(self):
        """Manual is_internal_transfer_manual overrides must never be
        touched by the tolerant matcher either."""
        conn = AsyncMock()
        await self._run(conn)
        tolerance_sql = conn.fetch.await_args_list[2].args[0]
        assert "is_internal_transfer_manual = FALSE" in tolerance_sql

    async def test_tolerance_sql_requires_different_accounts(self):
        """Self-matches are impossible but the predicate is defence-in-depth."""
        conn = AsyncMock()
        await self._run(conn)
        tolerance_sql = conn.fetch.await_args_list[2].args[0]
        assert "i.account_id <> o.account_id" in tolerance_sql

    async def test_tolerance_sql_requires_known_family_owners(self):
        """Same-family rule: both sides must resolve to a user via the
        accounts.user_id → plaid_items.user_id fallback."""
        conn = AsyncMock()
        await self._run(conn)
        tolerance_sql = conn.fetch.await_args_list[2].args[0]
        assert "o.owner_uid IS NOT NULL" in tolerance_sql
        assert "i.owner_uid IS NOT NULL" in tolerance_sql

    async def test_tolerance_sql_prefers_smallest_delta_first(self):
        """Tie-breaking: if an outflow has both a cent-exact and a
        fee-adjusted candidate, ROW_NUMBER must pick the cent-exact one."""
        conn = AsyncMock()
        await self._run(conn)
        tolerance_sql = conn.fetch.await_args_list[2].args[0]
        # Primary sort key is the amount delta — so ABS(o+i) leads the ORDER BY.
        assert (
            "ORDER BY ABS(o.amount_cents + i.amount_cents), ABS(o.date - i.date), i.id"
            in tolerance_sql
        )
        assert (
            "ORDER BY ABS(o.amount_cents + i.amount_cents), ABS(o.date - i.date), o.id"
            in tolerance_sql
        )

    async def test_tolerance_sql_only_runs_on_plaid_rows(self):
        """Cash / manual-import transactions don't have a counterparty to
        match against, so the candidate pool stays Plaid-only."""
        conn = AsyncMock()
        await self._run(conn)
        tolerance_sql = conn.fetch.await_args_list[2].args[0]
        assert "'plaid'" in tolerance_sql and "'plaid_sandbox'" in tolerance_sql

    async def test_tolerance_skipped_when_horizon_non_positive(self):
        """match_pairs already bails out when horizon<=0 — the tolerance
        pass must honour that contract."""
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        assert await match_pairs(conn, horizon_days=0) == set()
        assert await match_pairs(conn, horizon_days=-1) == set()
        assert conn.fetch.await_count == 0


@pytest.mark.asyncio
class TestMatchPairsToleranceBehaviour:
    """End-to-end behaviour: the paired set should include both exact and
    tolerant matches, with exact precedence."""

    async def test_union_of_exact_and_tolerant_matches(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            side_effect=[
                [{"out_id": 101, "in_id": 102}],  # cash↔debt exact
                [{"out_id": 201, "in_id": 202}],  # depo↔depo exact
                [{"out_id": 377, "in_id": 907}],  # depo↔depo tolerant
            ]
        )
        paired = await match_pairs(conn, horizon_days=90)
        assert paired == {101, 102, 201, 202, 377, 907}

    async def test_tolerance_receives_paired_ids_from_earlier_passes(self):
        """The 3rd call's $2 parameter must be a list of every id already
        paired — so the tolerant matcher never re-pairs them."""
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            side_effect=[
                [{"out_id": 101, "in_id": 102}],  # cash↔debt exact
                [{"out_id": 201, "in_id": 202}],  # depo↔depo exact
                [],                                # tolerance — nothing to do
            ]
        )
        await match_pairs(conn, horizon_days=90)

        tolerance_args = conn.fetch.await_args_list[2].args
        # args == (sql, horizon_days, already_paired_ids_list)
        assert tolerance_args[1] == 90
        assert sorted(tolerance_args[2]) == [101, 102, 201, 202]

    async def test_empty_paired_set_on_cold_start(self):
        """Fresh family with no Plaid data — tolerance pass runs but finds
        nothing, returns an empty set."""
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        assert await match_pairs(conn, horizon_days=90) == set()
        # Still ran all three passes.
        assert conn.fetch.await_count == 3
