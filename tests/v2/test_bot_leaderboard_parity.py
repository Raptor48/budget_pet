"""
Bot leaderboard ↔ /reports parity.

Before V2.3 hot-fix the bot's per-category leaderboard read transactions
directly with ``t.date >= …`` (raw posted date, not authorized) and no
sandbox filter, no splits handling. In sandbox demos and on transactions
posted a day after authorization that broke parity with the canonical
``/api/reports/by-category`` view: same household, same week, two
different totals — depending on which screen the user was looking at.

These tests pin the SQL the bot emits to the same parity rules used by
the canonical reports queries so the two views can never silently drift.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from web import env_flags
from web.bot_api.repo import BotRepository


class TestLeaderboardParityWithReports:
    @pytest.mark.asyncio
    async def test_per_user_query_is_split_and_sandbox_aware(self):
        repo = BotRepository()
        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetch(sql, *args, **kwargs):
            captured["sql"] = sql
            captured["args"] = args
            return []

        conn.fetch = fake_fetch

        with patch.object(env_flags, "reports_include_plaid_sandbox", return_value=False):
            await repo._leaderboard_query(
                conn, date(2026, 4, 1), date(2026, 4, 8)
            )

        sql = captured["sql"]
        # Splits handling — same UNION ALL pattern reports use.
        assert "UNION ALL" in sql
        assert "FROM transaction_splits" in sql
        assert "NOT EXISTS (" in sql and "transaction_splits" in sql
        # Authorized-date convention.
        assert "COALESCE(t.authorized_date, t.date)" in sql
        # Sandbox parity (sandbox-include OFF → exclude clause must appear).
        assert "'plaid_sandbox'" in sql
        # No COALESCE-on-class hack hiding NULL transaction_class.
        assert "COALESCE(t.transaction_class, 'expense')" not in sql
        assert "t.transaction_class = 'expense'" in sql

    @pytest.mark.asyncio
    async def test_household_query_is_split_and_sandbox_aware(self):
        repo = BotRepository()
        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetch(sql, *args, **kwargs):
            captured["sql"] = sql
            return []

        conn.fetch = fake_fetch

        with patch.object(env_flags, "reports_include_plaid_sandbox", return_value=False):
            await repo._leaderboard_household_query(
                conn, date(2026, 4, 1), date(2026, 4, 8)
            )

        sql = captured["sql"]
        assert "UNION ALL" in sql
        assert "FROM transaction_splits" in sql
        assert "COALESCE(t.authorized_date, t.date)" in sql
        assert "'plaid_sandbox'" in sql
        assert "COALESCE(t.transaction_class, 'expense')" not in sql
        assert "t.transaction_class = 'expense'" in sql

    @pytest.mark.asyncio
    async def test_sandbox_include_drops_exclude_clause(self):
        """When PLAID_ENV=sandbox (or override is on) the sandbox filter
        must NOT appear — otherwise demo banks would silently disappear
        from the bot leaderboard."""
        repo = BotRepository()
        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetch(sql, *args, **kwargs):
            captured["sql"] = sql
            return []

        conn.fetch = fake_fetch

        with patch.object(env_flags, "reports_include_plaid_sandbox", return_value=True):
            await repo._leaderboard_query(
                conn, date(2026, 4, 1), date(2026, 4, 8)
            )

        # Sandbox include ON: no exclusion clause. The string 'plaid_sandbox'
        # must not appear in the SQL at all.
        assert "'plaid_sandbox'" not in captured["sql"]
