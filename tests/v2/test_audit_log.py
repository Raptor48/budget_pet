"""Tests for the audit_log module."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web.audit.repo import AuditRepository
from web.audit.service import record as audit_record
from tests.v2.conftest import make_mock_pool


class TestAuditRepository:
    @pytest.mark.asyncio
    async def test_insert_persists_metadata_as_jsonb(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow = AsyncMock(return_value={"id": 7})

        repo = AuditRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            row_id = await repo.insert(
                event_type="plaid.sync_manual",
                source="manual",
                actor_user_id=1,
                actor_username="denis",
                metadata={"items_synced": 2},
                request_ip="127.0.0.1",
            )

        assert row_id == 7
        # The INSERT uses $7::jsonb; the repo passes a JSON string for that slot.
        args = conn.fetchrow.await_args.args
        assert args[3] == "plaid.sync_manual"
        assert args[4] == "manual"
        assert '"items_synced": 2' in args[7]

    @pytest.mark.asyncio
    async def test_insert_rejects_invalid_source(self):
        repo = AuditRepository()
        with pytest.raises(ValueError):
            await repo.insert(event_type="x", source="hacker")

    @pytest.mark.asyncio
    async def test_list_applies_category_prefix_and_cursor(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch = AsyncMock(return_value=[])

        repo = AuditRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            await repo.list(limit=25, before_id=100, event_prefix="plaid.")

        args = conn.fetch.await_args.args
        query = args[0]
        params = list(args[1:])

        assert "id < $1" in query
        assert "event_type LIKE $2" in query
        assert "ORDER BY id DESC" in query
        assert params[0] == 100
        assert params[1] == "plaid.%"
        assert params[-1] == 25

    @pytest.mark.asyncio
    async def test_list_decodes_json_metadata(self):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "created_at": None,
                    "actor_user_id": None,
                    "actor_username": None,
                    "event_type": "plaid.sync_scheduled",
                    "source": "scheduler",
                    "target_kind": None,
                    "target_id": None,
                    "metadata": '{"transactions_added": 4}',
                    "request_ip": None,
                }
            ]
        )

        repo = AuditRepository()
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            rows = await repo.list()

        assert rows[0]["metadata"] == {"transactions_added": 4}


class TestAuditRecordHelper:
    @pytest.mark.asyncio
    async def test_record_never_raises_when_db_fails(self):
        """Product flows should keep working even if audit writes blow up."""

        class FailingRepo:
            async def insert(self, **_):
                raise RuntimeError("db exploded")

        with patch("web.audit.service.get_audit_repo", return_value=FailingRepo()):
            # Must not raise.
            result = await audit_record("plaid.sync_manual", source="manual")

        assert result is None

    @pytest.mark.asyncio
    async def test_record_pulls_actor_and_ip_from_request(self):
        captured: dict = {}

        class FakeRepo:
            async def insert(self, **kwargs):
                captured.update(kwargs)
                return 1

        class FakeState:
            user = {"id": 42, "username": "denis"}

        class FakeClient:
            host = "198.51.100.5"

        fake_request = MagicMock()
        fake_request.state = FakeState()
        fake_request.headers = {"X-Forwarded-For": "203.0.113.1, 198.51.100.5"}
        fake_request.client = FakeClient()

        with patch("web.audit.service.get_audit_repo", return_value=FakeRepo()):
            await audit_record(
                "plaid.item_connect",
                source="manual",
                request=fake_request,
                metadata={"institution": "Test"},
            )

        assert captured["event_type"] == "plaid.item_connect"
        assert captured["source"] == "manual"
        assert captured["actor_user_id"] == 42
        assert captured["actor_username"] == "denis"
        # X-Forwarded-For "a, b" → we take the last one (the real client IP).
        assert captured["request_ip"] == "198.51.100.5"
        assert captured["metadata"] == {"institution": "Test"}
