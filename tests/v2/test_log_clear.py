"""
Clear-log repository helpers. The routes layer adds owner-only auth and
writes a final audit.log_cleared row — that's covered by route-level
tests in ``test_log_clear_routes.py``.
"""
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.audit.repo import AuditRepository
from web.plaid.repo import PlaidRepository


class TestAuditRepositoryDelete:
    @pytest.mark.asyncio
    async def test_delete_all_rows_returns_count(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock(return_value="DELETE 42")

        repo = AuditRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            deleted = await repo.delete()

        assert deleted == 42
        sql, *args = conn.execute.await_args.args
        assert sql.strip().startswith("DELETE FROM audit_log")
        # No filter clauses → empty WHERE.
        assert "WHERE" not in sql
        assert args == []

    @pytest.mark.asyncio
    async def test_delete_with_prefix_filter(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock(return_value="DELETE 7")

        repo = AuditRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            deleted = await repo.delete(event_prefix="plaid.")

        assert deleted == 7
        sql, *args = conn.execute.await_args.args
        assert "event_type LIKE $1" in sql
        assert args == ["plaid.%"]

    @pytest.mark.asyncio
    async def test_delete_with_before_cutoff(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock(return_value="DELETE 3")

        repo = AuditRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            deleted = await repo.delete(before_id=500)

        assert deleted == 3
        sql, *args = conn.execute.await_args.args
        assert "id < $1" in sql
        assert args == [500]

    @pytest.mark.asyncio
    async def test_delete_returns_zero_on_weird_status(self):
        """Unknown tag ⇒ deleted=0 rather than raising."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock(return_value="")

        repo = AuditRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            assert await repo.delete() == 0


class TestPlaidSyncLogDelete:
    @pytest.mark.asyncio
    async def test_clear_sync_log_returns_count(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock(return_value="DELETE 123")

        repo = PlaidRepository()
        with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)):
            deleted = await repo.clear_sync_log()

        assert deleted == 123
        sql, *_ = conn.execute.await_args.args
        assert sql.strip().startswith("DELETE FROM plaid_sync_log")

    @pytest.mark.asyncio
    async def test_clear_sync_log_handles_empty_tag(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.execute = AsyncMock(return_value="DELETE 0")

        repo = PlaidRepository()
        with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)):
            assert await repo.clear_sync_log() == 0
