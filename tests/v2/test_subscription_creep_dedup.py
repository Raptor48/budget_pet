"""
Regression coverage for the "same price-change line every morning" bug.

`detect_subscription_changes` used to decide a stream had a price change
purely by comparing the two latest price snapshots. `record_recurring_amount`
is a no-op when the amount is unchanged, so once Plaid reported a new price
the snapshot history froze at ``[new, old]`` forever, `is_price_change`
stayed True, and the 24h `notifications_queue` dedup expired nightly — so
the same "Con Edison $133.66 -> $134.57" line shipped in the morning brief
every single day.

Fix has two parts, both pinned here:
  * a per-snapshot `alerted_at` stamp — once we push an alert for a given
    price, the next producer pass skips it;
  * a significance gate — sub-threshold wobble (a $0.91 swing on a $133
    utility bill) never reaches the queue at all.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.notifications.producers import _price_change_is_significant


# ---------------------------------------------------------------------------
# _price_change_is_significant — the noise gate
# ---------------------------------------------------------------------------


class TestPriceChangeSignificance:
    def test_tiny_utility_wobble_is_noise(self):
        # The actual Con Edison case: $0.91 on $133.66 == 0.68%. Below
        # both the 3% and the $1.00 default floors.
        assert _price_change_is_significant(91, 13366) is False

    def test_big_percent_on_small_sub_alerts(self):
        # $0.50 on a $5.00 sub == 10% — clears the relative floor.
        assert _price_change_is_significant(50, 500) is True

    def test_big_absolute_on_large_bill_alerts(self):
        # $4.00 on a $400 bill == 1% (below the pct floor) but $4.00
        # clears the absolute floor.
        assert _price_change_is_significant(400, 40000) is True

    def test_sign_is_ignored(self):
        # A price *drop* of the same magnitude is just as significant.
        assert _price_change_is_significant(-50, 500) is True
        assert _price_change_is_significant(-91, 13366) is False

    def test_zero_base_is_not_suppressed(self):
        # Can't compute a ratio against a zero base — let it through.
        assert _price_change_is_significant(500, 0) is True

    def test_env_override_relaxes_floor(self, monkeypatch):
        # Drop the pct floor to 0.5% — now the $0.91 wobble clears it.
        monkeypatch.setenv("BOT_PRICE_CHANGE_MIN_PCT", "0.5")
        assert _price_change_is_significant(91, 13366) is True

    def test_env_override_garbage_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("BOT_PRICE_CHANGE_MIN_PCT", "not-a-number")
        monkeypatch.setenv("BOT_PRICE_CHANGE_MIN_ABS_CENTS", "also-bad")
        # Falls back to 3.0 / 100 — the utility wobble stays noise.
        assert _price_change_is_significant(91, 13366) is False


# ---------------------------------------------------------------------------
# detect_subscription_changes — the producer
# ---------------------------------------------------------------------------


def _stream_row(**overrides):
    base = {
        "id": 5,
        "description": "Con Edison",
        "merchant_name": "Con Edison",
        "last_amount_cents": 13457,
        "subscription_alerted_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "alias_display": None,
    }
    base.update(overrides)
    return base


def _history(current_alerted, *, current=13457, previous=13366):
    """Two-snapshot history as get_recurring_price_history returns it.
    history[0] is the current price's snapshot, history[1] the previous."""
    return [
        {
            "amount_cents": current,
            "currency": "USD",
            "observed_at": datetime(2026, 5, 8, tzinfo=timezone.utc),
            "alerted_at": (
                datetime(2026, 5, 8, tzinfo=timezone.utc)
                if current_alerted
                else None
            ),
        },
        {
            "amount_cents": previous,
            "currency": "USD",
            "observed_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
            "alerted_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
        },
    ]


def _make_repo(history):
    repo = AsyncMock()
    repo.get_recurring_price_history = AsyncMock(return_value=history)
    repo.record_recurring_amount = AsyncMock()
    repo.is_alert_enabled = AsyncMock(return_value=True)
    repo.mark_subscription_alerted = AsyncMock()
    repo.mark_recurring_price_alerted = AsyncMock()
    return repo


async def _run_producer(conn, repo):
    pool = make_mock_pool(conn)
    with (
        patch(
            "web.notifications.producers.get_pool",
            AsyncMock(return_value=pool),
        ),
        patch("web.notifications.producers.get_bot_repo", return_value=repo),
        patch(
            "web.notifications.producers.enqueue_notification",
            AsyncMock(return_value=1),
        ) as enqueue,
    ):
        from web.notifications.producers import detect_subscription_changes

        fired = await detect_subscription_changes()
    return fired, enqueue


class TestDetectSubscriptionChanges:
    @pytest.mark.asyncio
    async def test_already_alerted_snapshot_is_skipped(self):
        """The core regression: a price change whose current snapshot is
        already stamped must NOT re-fire, even though is_price_change is
        still structurally True."""
        conn = AsyncMock()
        conn.fetch.side_effect = [[_stream_row()], [{"id": 1}]]
        repo = _make_repo(_history(current_alerted=True))

        fired, enqueue = await _run_producer(conn, repo)

        assert fired == 0
        enqueue.assert_not_awaited()
        repo.mark_recurring_price_alerted.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_significant_unalerted_change_fires_and_stamps(self):
        """A real, significant price change with an un-stamped snapshot
        fires once and then stamps the snapshot so the next pass skips."""
        conn = AsyncMock()
        conn.fetch.side_effect = [[_stream_row(last_amount_cents=15000)], [{"id": 1}]]
        # 13366 -> 15000 == +12.2%, clearly significant.
        repo = _make_repo(
            _history(current_alerted=False, current=15000, previous=13366)
        )

        fired, enqueue = await _run_producer(conn, repo)

        assert fired == 1
        enqueue.assert_awaited_once()
        repo.mark_recurring_price_alerted.assert_awaited_once_with(5)

    @pytest.mark.asyncio
    async def test_subthreshold_change_is_suppressed(self):
        """The $0.91-on-$133 wobble: un-stamped snapshot, but the delta is
        below both floors — no enqueue, and crucially no stamp (so a later
        larger move from the same baseline can still alert)."""
        conn = AsyncMock()
        conn.fetch.side_effect = [[_stream_row()], [{"id": 1}]]
        repo = _make_repo(
            _history(current_alerted=False, current=13457, previous=13366)
        )

        fired, enqueue = await _run_producer(conn, repo)

        assert fired == 0
        enqueue.assert_not_awaited()
        repo.mark_recurring_price_alerted.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_records_amount_before_reading_history(self):
        """Ordering guard: record_recurring_amount must run BEFORE
        get_recurring_price_history, otherwise history[0] isn't guaranteed
        to be the current price's snapshot and the alerted_at check is
        meaningless."""
        conn = AsyncMock()
        conn.fetch.side_effect = [[_stream_row()], [{"id": 1}]]
        repo = _make_repo(_history(current_alerted=True))

        call_order: list[str] = []
        repo.record_recurring_amount.side_effect = (
            lambda *a, **k: call_order.append("record")
        )

        async def _history_side_effect(*_a, **_k):
            call_order.append("history")
            return _history(current_alerted=True)

        repo.get_recurring_price_history.side_effect = _history_side_effect

        await _run_producer(conn, repo)

        assert call_order == ["record", "history"]


# ---------------------------------------------------------------------------
# BotRepository.mark_recurring_price_alerted — the stamp helper
# ---------------------------------------------------------------------------


class TestMarkRecurringPriceAlerted:
    @pytest.mark.asyncio
    async def test_stamps_latest_snapshot_only(self):
        """The UPDATE must target only the newest snapshot for the stream
        and only when it's still NULL — a fresh price change (new snapshot
        row) must stay un-stamped so it can alert exactly once."""
        from web.bot_api.repo import BotRepository

        conn = AsyncMock()
        pool = make_mock_pool(conn)
        with patch(
            "web.bot_api.repo.get_pool", AsyncMock(return_value=pool)
        ):
            await BotRepository().mark_recurring_price_alerted(5)

        sql = conn.execute.call_args.args[0]
        normalised = " ".join(sql.split())
        assert "UPDATE recurring_price_snapshots" in normalised
        assert "SET alerted_at = NOW()" in normalised
        assert "ORDER BY observed_at DESC" in normalised
        assert "LIMIT 1" in normalised
        assert "alerted_at IS NULL" in normalised
        assert conn.execute.call_args.args[1] == 5
