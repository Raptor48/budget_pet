"""
Brief dispatcher: send-once-per-day regression coverage.

The dispatcher fires every minute and the brief window is 15 minutes
wide. On Sunday the early-return guard ("no pending rows ⇒ skip") is
bypassed because the Sunday brief always carries the streak summary +
audit invite even with zero queue items. Without a per-day sentinel that
caused one Sunday brief to be sent every minute for the whole window —
the user reported five "Sunday brief" pushes back-to-back at 8:30, 8:31,
8:32, 8:33, 8:34.

Fix is gated on ``couple_settings.last_brief_sent_date``: skip the brief
block entirely when it equals today's local date. After a successful
send the dispatcher stamps the column. These tests pin both halves of
that contract.
"""
from datetime import date, time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Common test helpers
# ---------------------------------------------------------------------------


def _make_settings(*, last_sent=None, sunday_enabled=True) -> dict:
    """Minimal settings dict mirroring ``BotRepository.get_couple_settings``."""
    return {
        "morning_brief_local": time(8, 30),
        "morning_brief_tz": "America/New_York",
        "quiet_hours_start": time(22, 0),
        "quiet_hours_end": time(8, 0),
        "sunday_brief_enabled": sunday_enabled,
        "last_brief_sent_date": last_sent,
    }


# A Sunday at 08:30 local, well inside the brief window. Pick a date with
# weekday()==6 so the dispatcher takes the Sunday-specific path.
SUNDAY_AT_BRIEF = "2025-11-30T08:30:00"  # Sunday
assert (
    __import__("datetime").datetime.fromisoformat(SUNDAY_AT_BRIEF).weekday() == 6
), "test fixture sanity"


def _patch_user_now(monkeypatch, iso_local: str):
    """Pin the dispatcher's idea of 'now in user's tz' regardless of host clock."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    fixed = datetime.fromisoformat(iso_local).replace(tzinfo=ZoneInfo("America/New_York"))

    from web.notifications import dispatcher

    monkeypatch.setattr(dispatcher, "_user_now", lambda _tz: fixed)


# ---------------------------------------------------------------------------
# 1. Skip path — sentinel already set for today
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_user_skips_when_brief_already_sent_today(monkeypatch):
    """The 2nd-through-15th-minute ticks of the brief window must not
    re-send. The dispatcher reads ``last_brief_sent_date`` from settings
    and bails before composing the message.
    """
    from web.notifications import dispatcher

    _patch_user_now(monkeypatch, SUNDAY_AT_BRIEF)

    repo = MagicMock()
    repo.get_couple_settings = AsyncMock(
        return_value=_make_settings(last_sent=date(2025, 11, 30))
    )
    repo.list_streaks = AsyncMock(return_value=[])
    repo.bump_streak = AsyncMock()
    repo.mark_brief_sent = AsyncMock()

    monkeypatch.setattr(dispatcher, "get_bot_repo", lambda: repo)
    monkeypatch.setattr(
        dispatcher, "list_pending_for_user", AsyncMock(return_value=[])
    )
    sender = AsyncMock()
    monkeypatch.setattr(dispatcher, "_send_to_chat", sender)

    await dispatcher._drain_user({"id": 1, "telegram_chat_id": 42})

    sender.assert_not_called()
    repo.mark_brief_sent.assert_not_called()
    repo.bump_streak.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Send path — first tick of the window stamps the date
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_user_sends_brief_and_stamps_today(monkeypatch):
    """When the sentinel is NULL (or yesterday), the Sunday brief is sent
    and ``mark_brief_sent`` is called with today's local date so the next
    minute's tick early-returns at the gate.
    """
    from web.notifications import dispatcher

    _patch_user_now(monkeypatch, SUNDAY_AT_BRIEF)

    repo = MagicMock()
    repo.get_couple_settings = AsyncMock(
        return_value=_make_settings(last_sent=None)
    )
    repo.list_streaks = AsyncMock(return_value=[])
    repo.bump_streak = AsyncMock()
    repo.mark_brief_sent = AsyncMock()

    monkeypatch.setattr(dispatcher, "get_bot_repo", lambda: repo)
    monkeypatch.setattr(
        dispatcher, "list_pending_for_user", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(dispatcher, "mark_sent", AsyncMock())
    sender = AsyncMock()
    monkeypatch.setattr(dispatcher, "_send_to_chat", sender)

    # Stub log_bot_activity — the import is module-level inside _drain_user
    # but the function is loaded lazily, so patching the source module
    # is the simplest way to keep it from hitting the DB.
    with patch("web.telegram.activity.log_bot_activity", new=AsyncMock()):
        await dispatcher._drain_user({"id": 7, "telegram_chat_id": 42})

    sender.assert_called_once()
    repo.mark_brief_sent.assert_awaited_once_with(7, date(2025, 11, 30))


# ---------------------------------------------------------------------------
# 3. Yesterday's stamp must not block today's brief
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_user_sends_when_last_sent_is_yesterday(monkeypatch):
    """Stale sentinel from a previous day must be ignored. The user gets
    today's brief on the first tick inside today's window."""
    from web.notifications import dispatcher

    _patch_user_now(monkeypatch, SUNDAY_AT_BRIEF)

    repo = MagicMock()
    repo.get_couple_settings = AsyncMock(
        return_value=_make_settings(last_sent=date(2025, 11, 29))
    )
    repo.list_streaks = AsyncMock(return_value=[])
    repo.bump_streak = AsyncMock()
    repo.mark_brief_sent = AsyncMock()

    monkeypatch.setattr(dispatcher, "get_bot_repo", lambda: repo)
    monkeypatch.setattr(
        dispatcher, "list_pending_for_user", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(dispatcher, "mark_sent", AsyncMock())
    sender = AsyncMock()
    monkeypatch.setattr(dispatcher, "_send_to_chat", sender)

    with patch("web.telegram.activity.log_bot_activity", new=AsyncMock()):
        await dispatcher._drain_user({"id": 7, "telegram_chat_id": 42})

    sender.assert_called_once()
    repo.mark_brief_sent.assert_awaited_once_with(7, date(2025, 11, 30))


# ---------------------------------------------------------------------------
# 4. Repo helper — UPSERT semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_brief_sent_upserts_with_today_date():
    """``mark_brief_sent`` must INSERT … ON CONFLICT DO UPDATE — never raise
    when the row is missing (fresh Telegram-link path) and never overwrite
    other columns on update.
    """
    from tests.v2.conftest import make_mock_pool
    from web.bot_api.repo import BotRepository

    conn = AsyncMock()
    captured: dict = {}

    async def execute(sql, *args):
        captured["sql"] = sql
        captured["args"] = args
        return "INSERT 0 1"

    conn.execute = AsyncMock(side_effect=execute)

    repo = BotRepository()
    with patch.object(repo, "_pool", AsyncMock(return_value=make_mock_pool(conn))):
        await repo.mark_brief_sent(42, date(2025, 11, 30))

    sql = captured["sql"]
    args = captured["args"]
    # The UPSERT pattern + the today date must be present; we don't lock
    # down whitespace, just the contract.
    assert "INSERT INTO couple_settings" in sql
    assert "ON CONFLICT (user_id) DO UPDATE" in sql
    assert "last_brief_sent_date" in sql
    assert 42 in args
    assert date(2025, 11, 30) in args
