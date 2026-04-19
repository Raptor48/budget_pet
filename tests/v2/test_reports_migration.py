"""
Migration guard for ``_migrate_transactions_transaction_class``.

The migration that introduces ``transactions.transaction_class`` +
``manual_class_override`` is critical: the rest of the reports math depends
on it running exactly once on legacy databases and being a no-op on fresh
installs. These tests pin the observable contract using a mocked asyncpg
connection — we don't have a live Postgres in unit tests, but the SQL
shape and the order of operations are easy to verify.

Covered:

    * Schema additions are idempotent (already-present columns are not
      re-created, index uses ``IF NOT EXISTS``).
    * Legacy ``is_internal_transfer_manual = TRUE`` rows get
      ``manual_class_override = 'internal_transfer'`` — user intent
      survives the switch to the four-class model.
    * Backfill via ``rescan_all`` only fires when no row has been
      classified yet; the gate is an ``EXISTS`` query, not the column
      existence flag.
    * Partial legacy overrides (manual=True, is_internal_transfer=False)
      are left alone — they mean "user said NOT an internal transfer" and
      we let the classifier decide.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web.migrations.v2_init import _migrate_transactions_transaction_class


class _ConnMock:
    """Minimal async connection mock that mimics asyncpg's async context
    manager for ``conn.transaction()`` and records executed SQL.

    Using a purpose-built class instead of ``AsyncMock`` because
    ``conn.transaction()`` must return an async context manager, and
    MagicMock's default behavior here is flaky across Python minor
    versions.
    """

    def __init__(self):
        self.executed_sql: list[str] = []
        self.ddl_sql: list[str] = []
        self.fetchval_returns: list = []
        self.fetchval_queries: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def transaction(self):
        return self

    async def fetchval(self, sql, *args, **kwargs):
        self.fetchval_queries.append(sql)
        if not self.fetchval_returns:
            return False
        return self.fetchval_returns.pop(0)

    async def execute(self, sql, *args, **kwargs):
        self.executed_sql.append(sql)
        return "OK"

    async def fetch(self, sql, *args, **kwargs):
        return []


class TestAddsColumnsAndIndex:
    @pytest.mark.asyncio
    async def test_first_run_creates_both_columns(self):
        """On a legacy DB (no ``transaction_class`` yet, no ``manual_class_override``
        yet) both columns get created and the index is created defensively
        with ``IF NOT EXISTS``."""
        conn = _ConnMock()
        # 1st fetchval: has_class_col → False (does not exist)
        # 2nd fetchval: has_override_col → False
        # 3rd fetchval: needs_backfill → False (so we don't try to run
        # the classifier against a pool we don't have here; that path is
        # tested below).
        conn.fetchval_returns = [False, False, False]

        captured_ddl: list[str] = []

        async def fake_ddl(_conn, sql):
            captured_ddl.append(sql)

        with patch("web.migrations.v2_init._ddl", side_effect=fake_ddl):
            await _migrate_transactions_transaction_class(conn)

        joined = "\n".join(captured_ddl)
        assert "ADD COLUMN manual_class_override TEXT NULL" in joined
        assert "ADD COLUMN transaction_class TEXT NOT NULL DEFAULT 'uncategorized'" in joined
        assert "CREATE INDEX IF NOT EXISTS idx_transactions_transaction_class" in joined

    @pytest.mark.asyncio
    async def test_idempotent_when_columns_exist(self):
        """On a freshly-migrated DB both columns already exist. The
        migration must not re-create them (that would fail on Postgres),
        only ensure the index is present."""
        conn = _ConnMock()
        conn.fetchval_returns = [True, True, False]  # has both, no backfill needed

        captured_ddl: list[str] = []

        async def fake_ddl(_conn, sql):
            captured_ddl.append(sql)

        with patch("web.migrations.v2_init._ddl", side_effect=fake_ddl):
            await _migrate_transactions_transaction_class(conn)

        joined = "\n".join(captured_ddl)
        assert "ADD COLUMN manual_class_override" not in joined
        assert "ADD COLUMN transaction_class" not in joined
        # Index creation is always attempted (IF NOT EXISTS makes it safe).
        assert "CREATE INDEX IF NOT EXISTS idx_transactions_transaction_class" in joined


class TestLegacyOverrideCarryOver:
    @pytest.mark.asyncio
    async def test_manual_internal_transfer_migrated(self):
        """Legacy `is_internal_transfer_manual = TRUE AND is_internal_transfer = TRUE`
        rows must become `manual_class_override = 'internal_transfer'`.
        This is the one-way bridge that preserves every user choice from
        the old toggle UI."""
        conn = _ConnMock()
        conn.fetchval_returns = [True, True, False]

        async def fake_ddl(_conn, sql):
            pass

        with patch("web.migrations.v2_init._ddl", side_effect=fake_ddl):
            await _migrate_transactions_transaction_class(conn)

        # The UPDATE must have run exactly once (see `conn.execute` log)
        # and must contain the guard so "auto = FALSE" legacy rows don't
        # get pinned as expense.
        assert len(conn.executed_sql) == 1
        sql = conn.executed_sql[0]
        assert "UPDATE transactions SET manual_class_override = 'internal_transfer'" in sql
        assert "is_internal_transfer_manual = TRUE" in sql
        assert "is_internal_transfer = TRUE" in sql
        # Idempotence guard: never overwrite a pre-existing override.
        assert "manual_class_override IS NULL" in sql


class TestBackfillGate:
    @pytest.mark.asyncio
    async def test_backfill_runs_when_no_rows_classified(self):
        """Fresh DB OR just-migrated legacy DB → every row has the default
        ``uncategorized`` class and no overrides yet → needs_backfill =
        TRUE → ``rescan_all`` is called with the whole history."""
        conn = _ConnMock()
        # has_class, has_override, needs_backfill
        conn.fetchval_returns = [True, True, True]

        async def fake_ddl(_conn, sql):
            pass

        mock_rescan = AsyncMock(return_value=MagicMock(
            total=0, changed=0, paired=0, by_class={},
        ))
        with patch("web.migrations.v2_init._ddl", side_effect=fake_ddl), \
             patch(
                 "web.classification.classifier.rescan_all", mock_rescan,
             ):
            await _migrate_transactions_transaction_class(conn)

        mock_rescan.assert_awaited_once()
        # horizon_days=None → scan entire history.
        kwargs = mock_rescan.await_args.kwargs
        assert kwargs.get("horizon_days") is None

    @pytest.mark.asyncio
    async def test_backfill_skipped_on_already_classified_db(self):
        """Re-running the migration on an already-classified DB must not
        re-rescan (it's expensive on large histories). The ``needs_backfill``
        gate is the protection."""
        conn = _ConnMock()
        conn.fetchval_returns = [True, True, False]

        async def fake_ddl(_conn, sql):
            pass

        mock_rescan = AsyncMock()
        with patch("web.migrations.v2_init._ddl", side_effect=fake_ddl), \
             patch(
                 "web.classification.classifier.rescan_all", mock_rescan,
             ):
            await _migrate_transactions_transaction_class(conn)

        mock_rescan.assert_not_awaited()
