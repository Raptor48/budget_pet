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
    async def test_no_drift_short_circuits(self):
        """Clean DB (no mismatched rows) → migration does a single EXISTS
        probe and returns. No expensive rescan. Critical for app startup
        cost on healthy installs."""
        conn = _ConnMock()
        conn.fetchval_returns = [False]  # has_drift = False

        mock_rescan = AsyncMock()
        with patch(
            "web.classification.classifier.rescan_all", mock_rescan,
        ):
            await _migrate_fix_internal_transfer_class_drift(conn)

        # The probe ran once.
        assert len(conn.fetchval_queries) == 1
        # The rescan was NOT called — drift backfill is a no-op when the
        # invariant already holds.
        mock_rescan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_drift_present_triggers_full_rescan(self):
        """When the EXISTS probe finds at least one mismatched row,
        ``rescan_all`` is invoked with ``horizon_days=None`` so the entire
        history is re-classified — that's the point of the backfill."""
        conn = _ConnMock()
        conn.fetchval_returns = [True]  # has_drift = True

        mock_rescan = AsyncMock(return_value=MagicMock(
            total=42, changed=3, paired=0, by_class={"internal_transfer": 3},
        ))
        with patch(
            "web.classification.classifier.rescan_all", mock_rescan,
        ):
            await _migrate_fix_internal_transfer_class_drift(conn)

        mock_rescan.assert_awaited_once()
        kwargs = mock_rescan.await_args.kwargs
        # Full history, not horizon-limited.
        assert kwargs.get("horizon_days") is None

    @pytest.mark.asyncio
    async def test_drift_probe_excludes_manual_overrides(self):
        """The probe must skip rows with ``manual_class_override IS NOT
        NULL`` or ``is_internal_transfer_manual = TRUE`` — the user
        explicitly pinned those, so any "drift" between the legacy and
        modern columns reflects user intent and must not be touched."""
        conn = _ConnMock()
        conn.fetchval_returns = [False]
        with patch("web.classification.classifier.rescan_all", AsyncMock()):
            await _migrate_fix_internal_transfer_class_drift(conn)

        probe_sql = conn.fetchval_queries[0]
        # The two guards must both appear; if either is missing the
        # backfill could re-classify a manual decision.
        assert "manual_class_override IS NULL" in probe_sql
        assert "is_internal_transfer_manual = FALSE" in probe_sql

    @pytest.mark.asyncio
    async def test_drift_probe_checks_both_directions(self):
        """The mismatch predicate uses ``<>`` so both
        (legacy=TRUE, class != internal) AND
        (legacy=FALSE, class = internal) are caught. The first form is
        the symptom we observed in production; the second is theoretical
        but the symmetric check is one keystroke and protects against
        future regressions."""
        conn = _ConnMock()
        conn.fetchval_returns = [False]
        with patch("web.classification.classifier.rescan_all", AsyncMock()):
            await _migrate_fix_internal_transfer_class_drift(conn)
        probe_sql = conn.fetchval_queries[0]
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
