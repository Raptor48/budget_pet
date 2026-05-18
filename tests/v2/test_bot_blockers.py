"""
Regression tests for the V2.3 bot stability fixes.

Three blockers were addressed in one sprint:

1. **Webhook idempotency.** Telegram retries deliveries that didn't get a
   200 in time; without dedup the same ``update_id`` ran handlers twice
   (double cash entry, double OCR billing). The webhook now claims the
   ``update_id`` against ``telegram_seen_updates`` and short-circuits
   replays.

2. **Permanent / rate-limit Telegram errors.** ``Forbidden`` (user blocked
   the bot) used to spam logs 1440x/day. ``RetryAfter`` used to drop the
   row into ``failed`` state. Both are now classified — permanent flips
   ``users.telegram_blocked`` and stops draining the user; rate-limit
   stamps ``not_before`` so the row waits out its embargo.

3. **Dispatcher heartbeat.** ``/api/telegram/health`` now exposes the
   timestamp of the last completed drain so an external uptime monitor
   can catch a silently stalled dispatcher.

These tests use the standard mock-pool harness — they pin behaviour, not
the exact SQL form.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool


class TestErrorClassifier:
    def test_forbidden_is_permanent(self):
        from web.notifications.dispatcher import _classify_telegram_error
        from telegram.error import Forbidden

        exc = Forbidden("bot was blocked by the user")
        assert _classify_telegram_error(exc) == "permanent"

    def test_chat_migrated_is_permanent(self):
        from web.notifications.dispatcher import _classify_telegram_error
        from telegram.error import ChatMigrated

        exc = ChatMigrated(new_chat_id=-100123)
        assert _classify_telegram_error(exc) == "permanent"

    def test_retry_after_is_retry_after(self):
        from web.notifications.dispatcher import _classify_telegram_error
        from telegram.error import RetryAfter

        exc = RetryAfter(30)
        assert _classify_telegram_error(exc) == "retry_after"

    def test_generic_exception_is_transient(self):
        from web.notifications.dispatcher import _classify_telegram_error

        assert _classify_telegram_error(RuntimeError("network blip")) == "transient"

    def test_string_match_fallback_for_blocked(self):
        """If python-telegram-bot is not importable in some test
        environments, the classifier still recognises the string form
        ``"blocked"`` to keep the path safe."""
        from web.notifications.dispatcher import _classify_telegram_error

        msg = RuntimeError("Forbidden: bot was blocked by the user")
        assert _classify_telegram_error(msg) == "permanent"


class TestRetryAfterSecondsClamping:
    def test_clamped_to_minimum(self):
        from web.notifications.dispatcher import _retry_after_seconds

        class Stub:
            retry_after = 1

        assert _retry_after_seconds(Stub()) == 15

    def test_honours_telegram_value(self):
        from web.notifications.dispatcher import _retry_after_seconds

        class Stub:
            retry_after = 90

        assert _retry_after_seconds(Stub()) == 90

    def test_clamped_to_one_hour(self):
        from web.notifications.dispatcher import _retry_after_seconds

        class Stub:
            retry_after = 9_999

        assert _retry_after_seconds(Stub()) == 3600

    def test_handles_missing_attribute(self):
        from web.notifications.dispatcher import _retry_after_seconds

        # Default to 60s when Telegram didn't say.
        assert _retry_after_seconds(RuntimeError("nope")) == 60


class TestQueueNotBeforeEmbargo:
    @pytest.mark.asyncio
    async def test_list_pending_filters_by_not_before(self):
        """``list_pending_for_user`` must include the ``not_before``
        embargo so a recently-deferred row doesn't reappear immediately."""
        from web.notifications.queue import list_pending_for_user

        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetch(sql, *args, **kwargs):
            captured["sql"] = sql
            return []

        conn.fetch = fake_fetch
        pool = make_mock_pool(conn)
        with patch("web.notifications.queue.get_pool", AsyncMock(return_value=pool)):
            await list_pending_for_user(42)
        assert "not_before IS NULL OR not_before <= NOW()" in captured["sql"]

    @pytest.mark.asyncio
    async def test_defer_until_emits_interval(self):
        from web.notifications.queue import defer_until

        captured: dict = {}
        conn = AsyncMock()

        async def fake_execute(sql, *args, **kwargs):
            captured["sql"] = sql
            captured["args"] = args
            return "UPDATE 1"

        conn.execute = fake_execute
        pool = make_mock_pool(conn)
        with patch("web.notifications.queue.get_pool", AsyncMock(return_value=pool)):
            await defer_until(7, 60)
        assert "not_before = NOW() + ($2 || ' seconds')::interval" in captured["sql"]
        assert captured["args"] == (7, 60)

    @pytest.mark.asyncio
    async def test_defer_until_zero_is_noop(self):
        from web.notifications.queue import defer_until

        # No DB hit when retry_after_seconds <= 0; we don't want to
        # accidentally clear an existing not_before.
        called = False

        async def fail(*_a, **_k):
            nonlocal called
            called = True
            return "UPDATE 0"

        with patch(
            "web.notifications.queue.get_pool",
            AsyncMock(side_effect=AssertionError("get_pool should not be called")),
        ):
            await defer_until(7, 0)
        assert called is False


class TestListUsersWithChatSkipsBlocked:
    @pytest.mark.asyncio
    async def test_query_filters_out_blocked(self):
        from web.bot_api.repo import BotRepository

        captured: dict = {}
        conn = AsyncMock()

        async def fake_fetch(sql, *args, **kwargs):
            captured["sql"] = sql
            return []

        conn.fetch = fake_fetch
        pool = make_mock_pool(conn)
        repo = BotRepository()
        # BotRepository._pool() reads from web.db.get_pool — patch the
        # symbol the repo actually imports.
        with patch("web.bot_api.repo.get_pool", AsyncMock(return_value=pool)):
            await repo.list_users_with_chat()
        sql = captured["sql"]
        assert "telegram_blocked" in sql
        # Must affirmatively exclude blocked users.
        assert "= FALSE" in sql


class TestWebhookIdempotency:
    @pytest.mark.asyncio
    async def test_claim_returns_true_on_first_insert(self):
        from web.telegram.router import _claim_update_id

        conn = AsyncMock()
        # ON CONFLICT DO NOTHING with RETURNING returns the row when
        # the insert actually happened.
        conn.fetchrow = AsyncMock(return_value={"update_id": 4242})
        pool = make_mock_pool(conn)
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            assert await _claim_update_id(4242) is True

    @pytest.mark.asyncio
    async def test_claim_returns_false_on_duplicate(self):
        from web.telegram.router import _claim_update_id

        conn = AsyncMock()
        # Conflict path: nothing returned.
        conn.fetchrow = AsyncMock(return_value=None)
        pool = make_mock_pool(conn)
        with patch("web.db.get_pool", AsyncMock(return_value=pool)):
            assert await _claim_update_id(4242) is False

    @pytest.mark.asyncio
    async def test_claim_falls_open_on_db_error(self):
        """If the dedup table is unreachable we'd rather risk a duplicate
        than silently swallow a real update."""
        from web.telegram.router import _claim_update_id

        with patch(
            "web.db.get_pool",
            AsyncMock(side_effect=RuntimeError("pool unavailable")),
        ):
            assert await _claim_update_id(7) is True


class TestDispatcherHeartbeat:
    def test_heartbeat_returns_initial_state(self):
        from web.notifications.dispatcher import get_dispatcher_heartbeat

        # Module-level state may have been mutated by other tests; just
        # make sure the keys are always present so the health endpoint
        # contract is stable.
        hb = get_dispatcher_heartbeat()
        assert set(hb.keys()) == {
            "last_drain_started_at",
            "last_drain_finished_at",
            "last_drain_duration_s",
            "last_drain_users",
        }

    @pytest.mark.asyncio
    async def test_drain_once_updates_heartbeat(self):
        """Even a no-user drain should bump the timestamp so the health
        endpoint can prove the dispatcher is alive."""
        from web.notifications import dispatcher as disp

        # Mock the bot repo so list_users_with_chat returns []
        repo = MagicMock()
        repo.list_users_with_chat = AsyncMock(return_value=[])
        with patch.object(disp, "get_bot_repo", return_value=repo):
            await disp._drain_once()
        hb = disp.get_dispatcher_heartbeat()
        assert hb["last_drain_finished_at"] is not None
        assert hb["last_drain_users"] == 0
