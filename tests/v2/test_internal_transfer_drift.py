"""
Regression tests for the legacy/modern internal-transfer drift fix
(2026-04-27).

Two paths must stay correct:

1. ``import_transactions`` (Plaid sync) reclassifies the **entire history**
   after each import, not just the last 7 days. Tested by inspecting the
   ``rescan_all`` call shape.

2. The one-shot ``_migrate_fix_internal_transfer_class_drift`` migration
   triggers a full rescan iff there's a row where ``is_internal_transfer``
   and ``transaction_class`` disagree. Idempotent: a clean DB results in
   zero rescan calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web.migrations.v2_init import _migrate_fix_internal_transfer_class_drift


class _ConnMock:
    """Same shape as the connection mock in test_reports_migration.py.
    Records SQL for assertion and serves canned ``fetchval`` returns in
    declaration order."""

    def __init__(self):
        self.executed_sql: list[str] = []
        self.fetchval_queries: list[str] = []
        self.fetchval_returns: list = []

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


# ---------------------------------------------------------------------------
# Drift backfill migration
# ---------------------------------------------------------------------------


class TestDriftBackfillMigration:
    @pytest.mark.asyncio
    async def test_first_run_forces_full_rescan_even_without_drift(self):
        """Critical: the column-drift probe alone misses rows whose
        legacy + modern columns are self-consistent but where the
        modern class is stale (e.g. rule 5.5 fired on a previous rescan
        and tagged a counterparty-bearing TRANSFER_IN as ``income``).
        On the first deploy of this fix the sentinel
        ``app_settings.itr_v2_rescan_done`` is FALSE → we force a full
        rescan unconditionally, then flip the flag so subsequent
        startups don't repeat the work."""
        conn = _ConnMock()
        # fetchval order: itr_v2_rescan_done (FALSE → first run),
        #                 has_drift (FALSE → no column drift, but we
        #                                    rescan anyway because of the flag)
        conn.fetchval_returns = [False, False]

        async def fake_ddl(_conn, sql):
            pass

        mock_rescan = AsyncMock(return_value=MagicMock(
            total=10, changed=3, paired=0, by_class={"internal_transfer": 3},
        ))
        with patch("web.migrations.v2_init._ddl", side_effect=fake_ddl), \
             patch("web.classification.classifier.rescan_all", mock_rescan):
            await _migrate_fix_internal_transfer_class_drift(conn)

        # Rescan ran with full history.
        mock_rescan.assert_awaited_once()
        assert mock_rescan.await_args.kwargs.get("horizon_days") is None
        # Sentinel was flipped to TRUE so the next startup skips.
        assert any(
            "UPDATE app_settings SET itr_v2_rescan_done = TRUE" in s
            for s in conn.executed_sql
        )

    @pytest.mark.asyncio
    async def test_steady_state_no_rescan(self):
        """After the first-run rescan has fired and there's no column
        drift, subsequent startups must skip the rescan to keep boot
        cost minimal. Two cheap fetchvals (sentinel + drift probe)
        and we're done."""
        conn = _ConnMock()
        # itr_v2_rescan_done = TRUE, has_drift = FALSE
        conn.fetchval_returns = [True, False]

        async def fake_ddl(_conn, sql):
            pass

        mock_rescan = AsyncMock()
        with patch("web.migrations.v2_init._ddl", side_effect=fake_ddl), \
             patch("web.classification.classifier.rescan_all", mock_rescan):
            await _migrate_fix_internal_transfer_class_drift(conn)

        mock_rescan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_drift_after_flag_set_still_triggers_rescan(self):
        """Even with the one-shot sentinel TRUE, a future drift
        (e.g. a regression that re-introduces the INSERT-skips-class
        bug) must re-trigger the rescan. The drift probe is the
        permanent safety net."""
        conn = _ConnMock()
        # itr_v2_rescan_done = TRUE, has_drift = TRUE
        conn.fetchval_returns = [True, True]

        async def fake_ddl(_conn, sql):
            pass

        mock_rescan = AsyncMock(return_value=MagicMock(
            total=42, changed=3, paired=0, by_class={"internal_transfer": 3},
        ))
        with patch("web.migrations.v2_init._ddl", side_effect=fake_ddl), \
             patch("web.classification.classifier.rescan_all", mock_rescan):
            await _migrate_fix_internal_transfer_class_drift(conn)

        mock_rescan.assert_awaited_once()
        # When triggered by drift (not first-run), the sentinel UPDATE
        # is NOT issued — it's already TRUE.
        assert not any(
            "UPDATE app_settings SET itr_v2_rescan_done = TRUE" in s
            for s in conn.executed_sql
        )

    @pytest.mark.asyncio
    async def test_drift_probe_excludes_manual_overrides(self):
        """The probe must skip rows with ``manual_class_override IS NOT
        NULL`` or ``is_internal_transfer_manual = TRUE`` — the user
        explicitly pinned those, so any "drift" between the legacy and
        modern columns reflects user intent and must not be touched."""
        conn = _ConnMock()
        # flag TRUE so we go straight to the drift probe path
        conn.fetchval_returns = [True, False]

        async def fake_ddl(_conn, sql):
            pass

        with patch("web.migrations.v2_init._ddl", side_effect=fake_ddl), \
             patch("web.classification.classifier.rescan_all", AsyncMock()):
            await _migrate_fix_internal_transfer_class_drift(conn)

        # Drift probe is the second fetchval after the sentinel read.
        probe_sql = conn.fetchval_queries[1]
        assert "manual_class_override IS NULL" in probe_sql
        assert "is_internal_transfer_manual = FALSE" in probe_sql

    @pytest.mark.asyncio
    async def test_drift_probe_checks_both_directions(self):
        """The mismatch predicate uses ``<>`` so both
        (legacy=TRUE, class != internal) AND
        (legacy=FALSE, class = internal) are caught."""
        conn = _ConnMock()
        conn.fetchval_returns = [True, False]

        async def fake_ddl(_conn, sql):
            pass

        with patch("web.migrations.v2_init._ddl", side_effect=fake_ddl), \
             patch("web.classification.classifier.rescan_all", AsyncMock()):
            await _migrate_fix_internal_transfer_class_drift(conn)
        probe_sql = conn.fetchval_queries[1]
        assert "is_internal_transfer <> (transaction_class = 'internal_transfer')" in probe_sql


# ---------------------------------------------------------------------------
# Post-import rescan horizon
# ---------------------------------------------------------------------------


class TestPostImportRescanHorizon:
    """The string assertion below is intentionally narrow: it pins the
    exact call shape the file at ``web/plaid/repo.py`` makes after every
    Plaid import. If a future agent re-introduces ``horizon_days=7``
    here (an easy "perf optimization" mistake), this test breaks loudly
    so they have to acknowledge the consistency trade-off documented in
    docs/categorization-precedence.md."""

    def test_repo_module_uses_full_horizon_after_import(self):
        # Import the module text rather than mock the whole sync flow —
        # the call site is well-isolated and grep-style assertions catch
        # the regression cheaply.
        from pathlib import Path

        repo_src = Path(
            "web/plaid/repo.py"
        ).read_text(encoding="utf-8")
        # The post-import call must be ``horizon_days=None``.
        assert "rescan_all(conn, horizon_days=None)" in repo_src
        # And the legacy 7-day shortcut must NOT come back.
        assert "rescan_all(conn, horizon_days=7)" not in repo_src
