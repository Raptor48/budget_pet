"""
Tests for the shared-expense lifecycle (Phase 1).

Covers the four surfaces that need to behave correctly together:

* :func:`web.finance.predicates.non_receivable_category_filter` — the
  one SQL helper that every income/expense aggregation consumes.

* :func:`web.transactions.shared_matcher.try_match_recent_inflows` —
  the auto-match decision rule (exact amount + unique outstanding +
  conservative on ambiguity).

* :class:`web.transactions.splits_repo.SplitsRepository` — propagates
  the new ``counterparty`` column through ``set_splits``.

* :class:`web.reports.repo.ReportsRepository` — the SQL queries now
  embed the receivable filter. Pinned via shape assertions on
  ``conn.fetch`` args.

These are pure mock-based unit tests; nothing hits a real DB. The
sequencing through asyncpg mocks mirrors the patterns established in
``test_recurring_unsubscribed.py`` and ``test_finance_predicates.py``.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool


def _attach_txn_ctx(conn: AsyncMock) -> None:
    """asyncpg's ``conn.transaction()`` returns a sync function whose
    result is an async context manager. AsyncMock defaults to a coroutine,
    which fails ``async with``. This helper patches it to behave correctly
    for any test that exercises code paths using ``async with
    conn.transaction()``."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=None)
    ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=ctx)


# ---------------------------------------------------------------------------
# Predicate helper
# ---------------------------------------------------------------------------


class TestNonReceivableCategoryFilter:
    def test_default_alias_is_c(self):
        from web.finance.predicates import non_receivable_category_filter

        sql = non_receivable_category_filter()
        # Defaults to ``c`` because every aggregator that JOINs categories
        # in this codebase already calls the alias ``c``.
        assert "c.is_receivable" in sql
        assert sql.startswith(" AND")

    def test_custom_alias(self):
        from web.finance.predicates import non_receivable_category_filter

        assert "sc.is_receivable" in non_receivable_category_filter("sc")
        assert "cb.is_receivable" in non_receivable_category_filter("cb")

    def test_no_alias_for_unaliased_queries(self):
        from web.finance.predicates import non_receivable_category_filter

        sql = non_receivable_category_filter("")
        # No "alias." prefix when alias=""; otherwise we'd produce
        # ``.is_receivable`` which is invalid SQL.
        assert "is_receivable" in sql
        assert ".is_receivable" not in sql

    def test_coalesce_handles_missing_join(self):
        """The filter must not blow up on a LEFT-joined row with no
        matching category (uncategorised transactions) — COALESCE
        treats NULL as non-receivable, so the row stays in."""
        from web.finance.predicates import non_receivable_category_filter

        sql = non_receivable_category_filter("c")
        assert "COALESCE(c.is_receivable, FALSE)" in sql


# ---------------------------------------------------------------------------
# Splits repo: counterparty round-trip
# ---------------------------------------------------------------------------


class TestSplitsRepoCounterparty:
    @pytest.mark.asyncio
    async def test_counterparty_round_trips_in_single_bulk_insert(self):
        """The repo must:
          (a) propagate ``counterparty`` end-to-end, and
          (b) do it via ONE bulk INSERT (UNNEST), not a per-row loop —
              the loop form held a row lock per iteration and tripped
              the 30s ``command_timeout`` whenever Plaid sync or the
              shared-expense matcher concurrently touched the same
              parent. Same lesson as the bulk-unsubscribe fix."""
        from web.transactions.splits_repo import SplitsRepository

        conn = AsyncMock()
        _attach_txn_ctx(conn)
        pool = make_mock_pool(conn)
        # set_splits flow: fetchrow(parent amount), then DELETE, then
        # ONE fetch(INSERT … RETURNING *) returning the inserted rows.
        conn.fetchrow.return_value = {"amount_cents": 20000}
        conn.fetch.return_value = [
            {
                "id": 1, "parent_transaction_id": 1, "category_id": 10,
                "tag_id": None, "amount_cents": 5000, "note": None,
                "counterparty": None, "auto_matched_at": None,
                "created_at": None,
            },
            {
                "id": 2, "parent_transaction_id": 1, "category_id": 99,
                "tag_id": None, "amount_cents": 15000, "note": None,
                "counterparty": "Alex", "auto_matched_at": None,
                "created_at": None,
            },
        ]

        with patch(
            "web.transactions.splits_repo.get_pool",
            AsyncMock(return_value=pool),
        ):
            result = await SplitsRepository().set_splits(
                transaction_id=1,
                splits=[
                    {"category_id": 10, "amount_cents": 5000},
                    {"category_id": 99, "amount_cents": 15000, "counterparty": "Alex"},
                ],
            )

        # Exactly ONE INSERT — pin the bulk shape so we don't silently
        # regress to a per-row loop.
        insert_calls = [
            c for c in conn.fetch.call_args_list
            if "INSERT INTO transaction_splits" in (c.args[0] if c.args else "")
        ]
        assert len(insert_calls) == 1
        sql, *args = insert_calls[0].args
        assert "UNNEST" in sql
        # Counterparty array is the 6th positional ($6); Alex must be in it.
        counterparties_arg = args[5]
        assert list(counterparties_arg) == [None, "Alex"]
        # And the returned rows are dicts with the new fields populated.
        assert result[1]["counterparty"] == "Alex"


# ---------------------------------------------------------------------------
# Reports SQL: receivable filter is in every aggregation
# ---------------------------------------------------------------------------


class TestReportsExcludeReceivable:
    """The math fix lives entirely in the SQL; pin the WHERE clauses so a
    refactor can't silently re-introduce the receivable double-count."""

    @pytest.mark.asyncio
    async def test_cash_flow_subtracts_receivable_splits(self):
        from web.reports.repo import ReportsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.return_value = {
            "income_cents": 0,
            "expenses_cents": 0,
            "internal_transfer_cents": 0,
        }
        with patch(
            "web.reports.repo.get_pool", AsyncMock(return_value=pool)
        ):
            await ReportsRepository().get_cash_flow("2026-05")
        sql = conn.fetchrow.call_args.args[0]
        # LATERAL precomputes receivable-split sum per parent
        assert "LEFT JOIN LATERAL" in sql
        assert "is_receivable = TRUE" in sql
        # Expense and income both NET the receivable carve-out
        assert "t.amount_cents - r.recv_cents" in sql  # expense
        assert "-t.amount_cents + r.recv_cents" in sql  # income
        # And the parent-level filter for whole-row receivable txns
        assert "COALESCE(c.is_receivable, FALSE)" in sql

    @pytest.mark.asyncio
    async def test_by_category_filters_receivable_in_both_legs(self):
        from web.reports.repo import ReportsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = []
        with patch(
            "web.reports.repo.get_pool", AsyncMock(return_value=pool)
        ):
            await ReportsRepository().get_by_category("2026-05")
        sql = conn.fetch.call_args.args[0]
        # Both UNION ALL legs reference is_receivable: one via alias ``c``
        # (parent leg), one via ``cs`` (splits leg).
        assert "c.is_receivable" in sql
        assert "cs.is_receivable" in sql

    @pytest.mark.asyncio
    async def test_income_breakdown_filters_receivable(self):
        from web.reports.repo import ReportsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = []
        with patch(
            "web.reports.repo.get_pool", AsyncMock(return_value=pool)
        ):
            await ReportsRepository().get_income_breakdown("2026-05")
        sql = conn.fetch.call_args.args[0]
        assert "c.is_receivable" in sql
        assert "cs.is_receivable" in sql

    @pytest.mark.asyncio
    async def test_top_merchants_excludes_receivable(self):
        from web.reports.repo import ReportsRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = []
        with patch(
            "web.reports.repo.get_pool", AsyncMock(return_value=pool)
        ):
            await ReportsRepository().get_top_merchants(month="2026-05")
        sql = conn.fetch.call_args.args[0]
        assert "LEFT JOIN categories c ON c.id = t.category_id" in sql
        assert "COALESCE(c.is_receivable, FALSE)" in sql


# ---------------------------------------------------------------------------
# Matcher: decision rule
# ---------------------------------------------------------------------------


class TestSharedMatcher:
    def _setup_pool_with_shared(self, conn) -> None:
        """Common AsyncMock wiring: pretend the Shared category id is 42."""
        conn.fetchval.return_value = 42

    @pytest.mark.asyncio
    async def test_unique_match_assigns_and_stamps(self):
        """The happy path: one outstanding receivable at exact amount in
        window → inflow gets re-categorised + a single auto-matched split
        is inserted."""
        from web.transactions.shared_matcher import try_match_recent_inflows

        conn = AsyncMock()
        _attach_txn_ctx(conn)
        pool = make_mock_pool(conn)
        # Sequence of fetchval results — the matcher calls fetchval in
        # this order: shared_id, amount-lookup-on-update, existing-split
        # check, parent-amount-fetch.
        # Easier: side_effect drives the queue.
        conn.fetchval.side_effect = [
            42,         # _shared_category_id
            None,       # _assign_to_shared: existing split? no
            -15000,     # _assign_to_shared: parent amount_cents
        ]
        # _list_unrouted_inflows returns one $150 inflow
        # _outstanding_count_at returns 1
        # _matched_counterparty returns "Alex"
        conn.fetch.side_effect = [
            [{
                "id": 5,
                "account_id": 7,
                "amount_cents": -15000,
                "effective_date": date(2026, 5, 12),
                "merchant_name": "Zelle Alex Petrov",
            }],
            [{"counterparty": "Alex"}],  # _matched_counterparty
        ]
        conn.fetchrow.return_value = {"outstanding": 1}

        with patch(
            "web.transactions.shared_matcher.get_pool",
            AsyncMock(return_value=pool),
        ):
            counters = await try_match_recent_inflows()

        assert counters["matched"] == 1
        assert counters["ambiguous"] == 0
        assert counters["no_match"] == 0
        # Both the UPDATE and the INSERT must have fired.
        executes = [c.args[0] for c in conn.execute.call_args_list]
        assert any("UPDATE transactions SET category_id" in s for s in executes)
        assert any("INSERT INTO transaction_splits" in s for s in executes)
        # And the INSERT carries counterparty = 'Alex' as the 4th arg
        insert_call = next(
            c for c in conn.execute.call_args_list
            if "INSERT INTO transaction_splits" in c.args[0]
        )
        assert insert_call.args[4] == "Alex"
        # auto_matched_at is set to NOW() in SQL, no positional arg
        assert "auto_matched_at" in insert_call.args[0]

    @pytest.mark.asyncio
    async def test_ambiguous_is_left_alone(self):
        """Two outstanding receivables at the same amount → the matcher
        must NOT auto-assign (would risk wrong attribution). Counter
        bumps, no DB writes."""
        from web.transactions.shared_matcher import try_match_recent_inflows

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchval.return_value = 42
        conn.fetch.return_value = [{
            "id": 5,
            "account_id": 7,
            "amount_cents": -5000,
            "effective_date": date(2026, 5, 12),
            "merchant_name": "Zelle",
        }]
        conn.fetchrow.return_value = {"outstanding": 2}

        with patch(
            "web.transactions.shared_matcher.get_pool",
            AsyncMock(return_value=pool),
        ):
            counters = await try_match_recent_inflows()

        assert counters["ambiguous"] == 1
        assert counters["matched"] == 0
        executes = [c.args[0] for c in conn.execute.call_args_list]
        assert not any("UPDATE transactions" in s for s in executes)

    @pytest.mark.asyncio
    async def test_no_outstanding_leaves_alone(self):
        from web.transactions.shared_matcher import try_match_recent_inflows

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchval.return_value = 42
        conn.fetch.return_value = [{
            "id": 5,
            "account_id": 7,
            "amount_cents": -5000,
            "effective_date": date(2026, 5, 12),
            "merchant_name": "Birthday gift",
        }]
        conn.fetchrow.return_value = {"outstanding": 0}

        with patch(
            "web.transactions.shared_matcher.get_pool",
            AsyncMock(return_value=pool),
        ):
            counters = await try_match_recent_inflows()

        assert counters["no_match"] == 1
        assert counters["matched"] == 0

    @pytest.mark.asyncio
    async def test_window_is_symmetric_around_inflow_date(self):
        """Pin the symmetric-window SQL shape so we never silently regress
        to a one-sided lookback. Original bug: a friend pre-paid Zelle
        on May 14 for the user's MTA charge that posted May 15 (still in
        pending). One-sided ``[inflow - N, inflow]`` window missed the
        outflow entirely — friend's payment sat as income forever."""
        from web.transactions.shared_matcher import try_match_recent_inflows

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchval.return_value = 42
        conn.fetch.return_value = [{
            "id": 5,
            "account_id": 7,
            "amount_cents": -9000,
            "effective_date": date(2026, 5, 14),
            "merchant_name": "Zelle Alisa",
        }]
        conn.fetchrow.return_value = {"outstanding": 0}

        with patch(
            "web.transactions.shared_matcher.get_pool",
            AsyncMock(return_value=pool),
        ):
            await try_match_recent_inflows()

        outstanding_sql = conn.fetchrow.call_args.args[0]
        # Both ends of the BETWEEN reference the lookback interval —
        # before AND after the inflow date. ``make_interval(days => $3)``
        # is used instead of the older ``($3 || ' days')::interval``
        # because the string-concat form forces $3 to text and asyncpg
        # rejects ints into text-inferred parameters (DataError that
        # silently killed the matcher in production for a week).
        assert outstanding_sql.count("make_interval(days => $3)") >= 2
        assert "+ make_interval(days => $3)" in outstanding_sql

    @pytest.mark.asyncio
    async def test_no_inflows_clean_noop(self):
        from web.transactions.shared_matcher import try_match_recent_inflows

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchval.return_value = 42
        conn.fetch.return_value = []

        with patch(
            "web.transactions.shared_matcher.get_pool",
            AsyncMock(return_value=pool),
        ):
            counters = await try_match_recent_inflows()

        assert counters == {
            "checked": 0, "matched": 0, "ambiguous": 0, "no_match": 0,
            "decisions": [],
        }

    @pytest.mark.asyncio
    async def test_shared_category_missing_is_safe_noop(self):
        """Defensive: if the migration hasn't run yet (no Shared category),
        the matcher logs a warning and returns zeros — must never crash."""
        from web.transactions.shared_matcher import try_match_recent_inflows

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchval.return_value = None  # _shared_category_id miss

        with patch(
            "web.transactions.shared_matcher.get_pool",
            AsyncMock(return_value=pool),
        ):
            counters = await try_match_recent_inflows()

        assert counters == {
            "checked": 0, "matched": 0, "ambiguous": 0, "no_match": 0,
            "decisions": [],
        }
        # No fetch / no execute should have happened — strictly the
        # shared_id probe and bail out.
        conn.fetch.assert_not_called()
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_unrouted_inflows_query_includes_internal_transfer(self):
        """Real-world bug: a friend's Zelle frequently gets pre-classified
        as ``internal_transfer`` (name-match on their first name, or
        Plaid's pair-matcher hitting an unrelated same-amount outflow).
        Scanning only ``income`` silently dropped those settlements
        forever. The broadened class predicate is what saves them — pin
        the SQL shape so a future "simplification" doesn't regress it."""
        from web.transactions.shared_matcher import try_match_recent_inflows

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchval.return_value = 42
        conn.fetch.return_value = []

        with patch(
            "web.transactions.shared_matcher.get_pool",
            AsyncMock(return_value=pool),
        ):
            await try_match_recent_inflows()

        # First .fetch() call is _list_unrouted_inflows
        list_sql = conn.fetch.call_args_list[0].args[0]
        assert "'income'" in list_sql
        assert "'uncategorized'" in list_sql
        assert "'internal_transfer'" in list_sql
        # And the splits-guard — never overwrite a manually-managed row.
        assert "NOT EXISTS" in list_sql
        assert "transaction_splits" in list_sql

    @pytest.mark.asyncio
    async def test_only_inflow_id_scopes_scan_to_single_row(self):
        """The manual debug endpoint passes ``only_inflow_id`` so the
        admin can re-check a single Zelle that they expected to match.
        Verify that filter is applied in Python (the listing query
        still scans the full window, but the in-memory filter cuts the
        decision loop down to one row)."""
        from web.transactions.shared_matcher import try_match_recent_inflows

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchval.return_value = 42
        conn.fetch.return_value = [
            {"id": 5, "account_id": 7, "amount_cents": -9000,
             "transaction_class": "income",
             "effective_date": date(2026, 5, 14), "merchant_name": "A",
             "category_id": None},
            {"id": 6, "account_id": 7, "amount_cents": -5000,
             "transaction_class": "income",
             "effective_date": date(2026, 5, 14), "merchant_name": "B",
             "category_id": None},
        ]
        conn.fetchrow.return_value = {"outstanding": 0}

        with patch(
            "web.transactions.shared_matcher.get_pool",
            AsyncMock(return_value=pool),
        ):
            counters = await try_match_recent_inflows(only_inflow_id=5)

        assert counters["checked"] == 1
        assert [d["id"] for d in counters["decisions"]] == [5]


# ---------------------------------------------------------------------------
# Window env override
# ---------------------------------------------------------------------------


class TestWindowDays:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("BOT_SHARED_MATCH_WINDOW_DAYS", raising=False)
        from web.transactions.shared_matcher import _window_days

        assert _window_days() == 4

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("BOT_SHARED_MATCH_WINDOW_DAYS", "10")
        from web.transactions.shared_matcher import _window_days

        assert _window_days() == 10

    def test_clamps_zero(self, monkeypatch):
        # A 0-day window matches nothing — refuse and clamp to 1.
        monkeypatch.setenv("BOT_SHARED_MATCH_WINDOW_DAYS", "0")
        from web.transactions.shared_matcher import _window_days

        assert _window_days() == 1

    def test_clamps_huge(self, monkeypatch):
        # A 365-day window would auto-match wholly unrelated payments.
        monkeypatch.setenv("BOT_SHARED_MATCH_WINDOW_DAYS", "365")
        from web.transactions.shared_matcher import _window_days

        assert _window_days() == 30

    def test_garbage_falls_back(self, monkeypatch):
        monkeypatch.setenv("BOT_SHARED_MATCH_WINDOW_DAYS", "not-a-number")
        from web.transactions.shared_matcher import _window_days

        assert _window_days() == 4
