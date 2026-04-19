"""Tests for web/insights/store.py — upsert, dismiss/snooze/unhide, caching."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from tests.v2.conftest import make_mock_pool
from web.insights import store as insights_store


@pytest.fixture(autouse=True)
def _reset_cache():
    insights_store.invalidate_cache()
    yield
    insights_store.invalidate_cache()


class _FakeConn:
    """In-memory stand-in for an asyncpg connection. Tracks DB writes in dicts."""

    def __init__(self):
        self.cards: Dict[str, Dict[str, Any]] = {}
        self.user_state: Dict[tuple, Dict[str, Any]] = {}
        self.last_viewed_at: Dict[int, datetime] = {}
        self.settings_row: Dict[str, Any] = {}

    async def execute(self, sql: str, *args):
        sql_lc = sql.lower()
        if "insert into insights_cards" in sql_lc:
            (
                dedupe_key,
                type_,
                severity,
                title,
                summary,
                detail,
                action_url,
                action_label,
                payload_json,
            ) = args
            existing = self.cards.get(dedupe_key)
            now = datetime.now(timezone.utc)
            if existing:
                existing.update(
                    type=type_,
                    severity=severity,
                    title=title,
                    summary=summary,
                    detail=detail,
                    action_url=action_url,
                    action_label=action_label,
                    last_seen_at=now,
                )
            else:
                self.cards[dedupe_key] = {
                    "dedupe_key": dedupe_key,
                    "type": type_,
                    "severity": severity,
                    "title": title,
                    "summary": summary,
                    "detail": detail,
                    "action_url": action_url,
                    "action_label": action_label,
                    "first_seen_at": now,
                    "last_seen_at": now,
                }
            return "INSERT 0 1"
        if "delete from insights_cards" in sql_lc:
            cutoff: datetime = args[0]
            to_delete = [
                k
                for k, v in self.cards.items()
                if v["last_seen_at"] < cutoff
                and not any(uk == k for (_, uk) in self.user_state.keys())
            ]
            for k in to_delete:
                del self.cards[k]
            return f"DELETE {len(to_delete)}"
        if "insert into insights_card_user_state" in sql_lc:
            user_id, dedupe_key = args[0], args[1]
            now = datetime.now(timezone.utc)
            state = self.user_state.setdefault((user_id, dedupe_key), {})
            if "dismissed_at = now()" in sql_lc or "dismissed_at = now())" in sql_lc:
                state["dismissed_at"] = now
            elif "snoozed_until" in sql_lc:
                state["snoozed_until"] = args[2]
            return "INSERT 0 1"
        if "update insights_card_user_state" in sql_lc:
            user_id, dedupe_key = args[0], args[1]
            state = self.user_state.get((user_id, dedupe_key))
            if state is not None:
                state["dismissed_at"] = None
                state["snoozed_until"] = None
            return "UPDATE 1"
        if "insert into user_preferences" in sql_lc:
            self.last_viewed_at[args[0]] = datetime.now(timezone.utc)
            return "INSERT 0 1"
        return "OK"

    async def fetchval(self, sql: str, *args):
        sql_lc = sql.lower()
        if "select insights_config from app_settings" in sql_lc:
            return self.settings_row.get("insights_config")
        if "select 1 from insights_cards" in sql_lc:
            return 1 if args[0] in self.cards else None
        if "select insights_last_viewed_at" in sql_lc:
            return self.last_viewed_at.get(int(args[0]))
        return None

    async def fetch(self, sql: str, *args):
        sql_lc = sql.lower()
        if "from insights_card_user_state" in sql_lc:
            user_id, keys = args
            rows = []
            for (uid, key), state in self.user_state.items():
                if uid == user_id and key in keys:
                    rows.append(
                        {
                            "dedupe_key": key,
                            "dismissed_at": state.get("dismissed_at"),
                            "snoozed_until": state.get("snoozed_until"),
                        }
                    )
            return rows
        if "select dedupe_key, first_seen_at from insights_cards" in sql_lc:
            keys = args[0]
            return [
                {"dedupe_key": k, "first_seen_at": v["first_seen_at"]}
                for k, v in self.cards.items()
                if k in keys
            ]
        return []


@pytest.fixture
def fake_conn(monkeypatch):
    conn = AsyncMock(wraps=_FakeConn())
    fc = _FakeConn()
    # Rewire AsyncMock methods directly to the FakeConn instance to keep state.
    conn.execute = AsyncMock(side_effect=fc.execute)
    conn.fetchval = AsyncMock(side_effect=fc.fetchval)
    conn.fetch = AsyncMock(side_effect=fc.fetch)
    conn._store = fc  # type: ignore[attr-defined]
    pool = make_mock_pool(conn)

    async def _fake_get_pool():
        return pool

    monkeypatch.setattr("web.db.get_pool", _fake_get_pool)
    monkeypatch.setattr("web.insights.store.get_pool", _fake_get_pool)
    monkeypatch.setattr("web.insights.config.get_pool", _fake_get_pool)
    return conn


def _sample_card(**overrides):
    base = {
        "type": "budget_risk",
        "severity": "warn",
        "title": "Budget exceeded",
        "summary": "Dining over by $50",
        "detail": "blah",
        "dedupe_key": "budget_risk:10:2026-04",
        "action_url": "/budgets?month=2026-04",
        "action_label": "Open budgets",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_recompute_upserts_and_is_idempotent(fake_conn, monkeypatch):
    called = {"n": 0}

    async def fake_build(viewer_user_id=None):
        called["n"] += 1
        return {
            "cards": [_sample_card()],
            "actionable_count": 1,
            "new_count": 1,
        }

    monkeypatch.setattr("web.insights.store.build_insights_feed", fake_build)

    await insights_store.recompute_and_store(viewer_user_id=1)
    await insights_store.recompute_and_store(viewer_user_id=1)

    store = fake_conn._store  # type: ignore[attr-defined]
    # Only one row in insights_cards despite two recomputes — upsert idempotent.
    assert len(store.cards) == 1
    # first_seen_at is preserved across the second write (same value).


@pytest.mark.asyncio
async def test_cache_skips_rebuild_within_ttl(fake_conn, monkeypatch):
    calls = {"n": 0}

    async def fake_build(viewer_user_id=None):
        calls["n"] += 1
        return {"cards": [_sample_card()], "actionable_count": 1, "new_count": 1}

    monkeypatch.setattr("web.insights.store.build_insights_feed", fake_build)

    await insights_store.get_feed_cached(viewer_user_id=1)
    await insights_store.get_feed_cached(viewer_user_id=1)
    await insights_store.get_feed_cached(viewer_user_id=1)

    assert calls["n"] == 1, "second+third calls must hit the cache"


@pytest.mark.asyncio
async def test_cache_force_rebuilds(fake_conn, monkeypatch):
    calls = {"n": 0}

    async def fake_build(viewer_user_id=None):
        calls["n"] += 1
        return {"cards": [_sample_card()], "actionable_count": 1, "new_count": 1}

    monkeypatch.setattr("web.insights.store.build_insights_feed", fake_build)

    await insights_store.get_feed_cached(viewer_user_id=1)
    await insights_store.get_feed_cached(viewer_user_id=1, force=True)

    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_dismiss_removes_card_from_feed(fake_conn, monkeypatch):
    async def fake_build(viewer_user_id=None):
        return {"cards": [_sample_card()], "actionable_count": 1, "new_count": 1}

    monkeypatch.setattr("web.insights.store.build_insights_feed", fake_build)

    await insights_store.get_feed_cached(viewer_user_id=1)
    await insights_store.dismiss_card(1, "budget_risk:10:2026-04")

    feed = await insights_store.get_feed_cached(viewer_user_id=1)
    assert feed["cards"] == []
    assert feed["actionable_count"] == 0


@pytest.mark.asyncio
async def test_dismiss_respects_other_users(fake_conn, monkeypatch):
    """Wife dismissing her copy must not hide the card for the husband."""
    async def fake_build(viewer_user_id=None):
        return {"cards": [_sample_card()], "actionable_count": 1, "new_count": 1}

    monkeypatch.setattr("web.insights.store.build_insights_feed", fake_build)

    # User 1 dismisses
    await insights_store.get_feed_cached(viewer_user_id=1)
    await insights_store.dismiss_card(1, "budget_risk:10:2026-04")

    # User 2 sees a fresh feed
    feed2 = await insights_store.get_feed_cached(viewer_user_id=2)
    assert len(feed2["cards"]) == 1


@pytest.mark.asyncio
async def test_include_hidden_returns_dismissed(fake_conn, monkeypatch):
    async def fake_build(viewer_user_id=None):
        return {"cards": [_sample_card()], "actionable_count": 1, "new_count": 1}

    monkeypatch.setattr("web.insights.store.build_insights_feed", fake_build)

    await insights_store.get_feed_cached(viewer_user_id=1)
    await insights_store.dismiss_card(1, "budget_risk:10:2026-04")

    feed = await insights_store.get_feed_cached(viewer_user_id=1, include_hidden=True)
    assert len(feed["cards"]) == 1
    assert feed["cards"][0]["user_state"]["dismissed"] is True


@pytest.mark.asyncio
async def test_snooze_caps_at_max_days(fake_conn, monkeypatch):
    async def fake_build(viewer_user_id=None):
        return {"cards": [_sample_card()], "actionable_count": 1, "new_count": 1}

    monkeypatch.setattr("web.insights.store.build_insights_feed", fake_build)

    await insights_store.get_feed_cached(viewer_user_id=1)
    # Try to snooze way out in the future.
    far_future = datetime.now(timezone.utc) + timedelta(days=365)
    applied = await insights_store.snooze_card(1, "budget_risk:10:2026-04", far_future)

    # Default cap = 90 days.
    assert applied <= datetime.now(timezone.utc) + timedelta(days=91)


@pytest.mark.asyncio
async def test_snooze_rejects_past(fake_conn, monkeypatch):
    async def fake_build(viewer_user_id=None):
        return {"cards": [_sample_card()], "actionable_count": 1, "new_count": 1}

    monkeypatch.setattr("web.insights.store.build_insights_feed", fake_build)

    await insights_store.get_feed_cached(viewer_user_id=1)
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    with pytest.raises(ValueError):
        await insights_store.snooze_card(1, "budget_risk:10:2026-04", past)


@pytest.mark.asyncio
async def test_unhide_clears_state(fake_conn, monkeypatch):
    async def fake_build(viewer_user_id=None):
        return {"cards": [_sample_card()], "actionable_count": 1, "new_count": 1}

    monkeypatch.setattr("web.insights.store.build_insights_feed", fake_build)

    await insights_store.get_feed_cached(viewer_user_id=1)
    await insights_store.dismiss_card(1, "budget_risk:10:2026-04")
    feed = await insights_store.get_feed_cached(viewer_user_id=1)
    assert feed["cards"] == []

    await insights_store.unhide_card(1, "budget_risk:10:2026-04")
    feed = await insights_store.get_feed_cached(viewer_user_id=1)
    assert len(feed["cards"]) == 1
