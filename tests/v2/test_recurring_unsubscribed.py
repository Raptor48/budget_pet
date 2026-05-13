"""
Tests for the ``user_status = 'unsubscribed'`` lifecycle.

Covers two surfaces:

* :mod:`web.recurring.repo` — the state transition itself: stamping
  ``unsubscribed_at``, computing ``unsubscribe_verify_after`` from the
  stream's cadence, and the inverse transitions (reactivate / cancel /
  pause) clearing the verifier metadata.

* :mod:`web.recurring.verifier` — the nightly resolution: cancel when
  no outflow posted, fire a P0 alert when a charge slipped through,
  honour the dedup window, and respect cadence policy (annually /
  unknown stay pending).

All tests run against AsyncMock connections — no live DB. The asyncpg
contract is "pool.acquire() is a sync function returning an async ctx
manager that yields a conn"; the ``make_mock_pool`` helper handles that.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.recurring.repo import (
    UNSUBSCRIBE_VERIFY_GRACE_DAYS,
    RecurringRepository,
    _compute_unsubscribe_verify_after,
)


# ---------------------------------------------------------------------------
# _compute_unsubscribe_verify_after
# ---------------------------------------------------------------------------


class TestVerifyAfterComputation:
    """Cadence-aware deadline computation. ANNUALLY / UNKNOWN deliberately
    return None — the verifier won't auto-flip those streams."""

    def test_monthly_one_full_cycle_plus_grace(self):
        last = date(2026, 3, 6)
        now = datetime(2026, 3, 20, tzinfo=timezone.utc)
        result = _compute_unsubscribe_verify_after(last, "MONTHLY", now=now)
        assert result is not None
        # Next future occurrence after 2026-03-20 is 2026-04-06.
        expected = datetime(
            2026, 4, 6 + UNSUBSCRIBE_VERIFY_GRACE_DAYS, tzinfo=timezone.utc
        )
        assert result == expected

    def test_weekly(self):
        last = date(2026, 5, 1)
        now = datetime(2026, 5, 2, tzinfo=timezone.utc)
        result = _compute_unsubscribe_verify_after(last, "WEEKLY", now=now)
        assert result is not None
        expected = datetime(
            2026, 5, 8 + UNSUBSCRIBE_VERIFY_GRACE_DAYS, tzinfo=timezone.utc
        )
        assert result == expected

    def test_biweekly(self):
        last = date(2026, 5, 1)
        now = datetime(2026, 5, 2, tzinfo=timezone.utc)
        result = _compute_unsubscribe_verify_after(last, "BIWEEKLY", now=now)
        assert result is not None
        expected = datetime(
            2026, 5, 15 + UNSUBSCRIBE_VERIFY_GRACE_DAYS, tzinfo=timezone.utc
        )
        assert result == expected

    def test_annually_returns_none(self):
        # We don't wait 13 months to auto-confirm. ANNUALLY streams stay
        # pending until the user finalises manually.
        assert (
            _compute_unsubscribe_verify_after(date(2026, 1, 1), "ANNUALLY") is None
        )

    def test_unknown_returns_none(self):
        # UNKNOWN cadence = irregular bills. "No charge this cycle" is
        # not a signal of cancellation, so don't auto-flip.
        assert (
            _compute_unsubscribe_verify_after(date(2026, 1, 1), "UNKNOWN") is None
        )

    def test_missing_last_date(self):
        assert _compute_unsubscribe_verify_after(None, "MONTHLY") is None

    def test_missing_frequency(self):
        assert _compute_unsubscribe_verify_after(date(2026, 1, 1), None) is None


# ---------------------------------------------------------------------------
# RecurringRepository.update_stream — transitions
# ---------------------------------------------------------------------------


def _row(**overrides):
    """Minimal recurring_streams row used by AsyncMock returns."""
    base = {
        "id": 42,
        "plaid_stream_id": "stream_42",
        "account_id": 7,
        "direction": "outflow",
        "description": "Netflix",
        "merchant_name": "Netflix",
        "frequency": "MONTHLY",
        "average_amount_cents": 1599,
        "last_amount_cents": 1599,
        "currency": "USD",
        "first_date": date(2025, 1, 6),
        "last_date": date(2026, 3, 6),
        "is_active": True,
        "status": "MATURE",
        "user_status": "active",
        "cancelled_at": None,
        "paused_until": None,
        "unsubscribed_at": None,
        "unsubscribe_verify_after": None,
        "unsubscribed_charge_alerted_at": None,
        "price_change_pct": None,
        "price_change_snoozed_until": None,
    }
    base.update(overrides)
    return base


class TestUpdateStreamUnsubscribe:
    @pytest.mark.asyncio
    async def test_unsubscribe_stamps_metadata(self):
        """user_status='unsubscribed' should stamp unsubscribed_at, compute
        verify_after, and clear cancelled_at + paused_until + the prior
        charge-alert stamp."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        # First call: get_stream() to read last_date+frequency.
        # Second call: the UPDATE … RETURNING *.
        seed = _row()
        updated = _row(user_status="unsubscribed", unsubscribed_at=datetime.now(timezone.utc))
        conn.fetchrow.side_effect = [seed, updated]

        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            result = await RecurringRepository().update_stream(
                42, {"user_status": "unsubscribed"}
            )

        assert result is not None
        # The UPDATE SQL was built with all the side-effect columns.
        update_call = conn.fetchrow.call_args_list[1]
        sql = update_call.args[0]
        for col in (
            "user_status",
            "unsubscribed_at",
            "unsubscribe_verify_after",
            "unsubscribed_charge_alerted_at",
            "cancelled_at",
            "paused_until",
        ):
            assert col in sql, f"UPDATE missing {col!r}: {sql}"

    @pytest.mark.asyncio
    async def test_reactivate_clears_verifier_metadata(self):
        """user_status='active' must wipe every verifier breadcrumb so the
        stream re-enters the forecast cleanly."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        updated = _row(user_status="active")
        conn.fetchrow.return_value = updated

        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            await RecurringRepository().update_stream(
                42, {"user_status": "active"}
            )

        sql = conn.fetchrow.call_args.args[0]
        for col in (
            "unsubscribed_at",
            "unsubscribe_verify_after",
            "unsubscribed_charge_alerted_at",
            "cancelled_at",
        ):
            assert col in sql, f"reactivate must wipe {col}: {sql}"

    @pytest.mark.asyncio
    async def test_cancel_clears_unsubscribe_state(self):
        """Force-cancel from 'unsubscribed' should drop verify_after so
        an immediate Plaid resync can't re-fire a charge alert."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.return_value = _row(user_status="cancelled")

        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            await RecurringRepository().update_stream(
                42, {"user_status": "cancelled"}
            )

        sql = conn.fetchrow.call_args.args[0]
        assert "cancelled_at" in sql
        assert "unsubscribed_at" in sql
        assert "unsubscribe_verify_after" in sql


# ---------------------------------------------------------------------------
# RecurringRepository.bulk_apply — unsubscribe action
# ---------------------------------------------------------------------------


class TestBulkUnsubscribe:
    @pytest.mark.asyncio
    async def test_bulk_unsubscribe_runs_per_row(self):
        """The unsubscribe bulk path needs cadence-aware verify_after per
        row, so it issues one UPDATE per id (not a single bulk UPDATE)."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        # Two rows, both MONTHLY but different last_date.
        meta_rows = [
            {"id": 11, "last_date": date(2026, 3, 6), "frequency": "MONTHLY"},
            {"id": 22, "last_date": date(2026, 3, 20), "frequency": "MONTHLY"},
        ]
        conn.fetch.return_value = meta_rows
        conn.fetchrow.side_effect = [{"id": 11}, {"id": 22}]

        with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
            updated = await RecurringRepository().bulk_apply(
                ids=[11, 22], action="unsubscribe"
            )

        assert updated == 2
        # Each per-row UPDATE carries verify_after as a positional arg.
        for call in conn.fetchrow.call_args_list:
            assert "user_status" in call.args[0]
            assert "unsubscribe_verify_after" in call.args[0]

    @pytest.mark.asyncio
    async def test_bulk_unknown_action_raises(self):
        with pytest.raises(ValueError):
            await RecurringRepository().bulk_apply(
                ids=[1], action="set_on_fire"
            )


# ---------------------------------------------------------------------------
# Forecast / Insights exclusion
# ---------------------------------------------------------------------------


class TestForecastExcludesUnsubscribed:
    def _stream(self, **overrides):
        base = {
            "id": 1,
            "is_active": True,
            "status": "MATURE",
            "direction": "outflow",
            "description": "Netflix",
            "merchant_name": "Netflix",
            "frequency": "MONTHLY",
            "last_date": date.today() - timedelta(days=5),
            "last_amount_cents": 1599,
            "average_amount_cents": 1599,
            "user_label": None,
            "user_status": "active",
        }
        base.update(overrides)
        return base

    def test_active_included(self):
        from web.reports.calculations import build_forecast

        entries = build_forecast([self._stream()], days=60)
        assert len(entries) == 1

    def test_unsubscribed_excluded(self):
        """The whole point of `unsubscribed` is "stop predicting this
        bill". Forecast must drop it even though `is_active` is still
        TRUE."""
        from web.reports.calculations import build_forecast

        entries = build_forecast(
            [self._stream(user_status="unsubscribed")], days=60
        )
        assert entries == []

    def test_paused_excluded(self):
        from web.reports.calculations import build_forecast

        entries = build_forecast(
            [self._stream(user_status="paused")], days=60
        )
        assert entries == []

    def test_cancelled_excluded(self):
        from web.reports.calculations import build_forecast

        entries = build_forecast(
            [self._stream(user_status="cancelled")], days=60
        )
        assert entries == []


# ---------------------------------------------------------------------------
# verifier.verify_unsubscribed_streams — outcomes
# ---------------------------------------------------------------------------


@pytest.fixture
def _verifier_stream():
    return {
        "id": 99,
        "account_id": 7,
        "plaid_stream_id": "s99",
        "merchant_name": "AT&T",
        "description": "AT&T BILL PAY",
        "frequency": "MONTHLY",
        "last_date": date(2026, 3, 6),
        "last_amount_cents": 7929,
        "average_amount_cents": 7929,
        "currency": "USD",
        "is_active": True,
        "plaid_status": "MATURE",
        "unsubscribed_at": datetime(2026, 3, 20, tzinfo=timezone.utc),
        "unsubscribed_charge_alerted_at": None,
        "owner_user_id": 1,
    }


class TestVerifier:
    @pytest.mark.asyncio
    async def test_no_charge_confirms_cancelled(self, _verifier_stream):
        """Happy path: verify window elapsed, no outflow posted since
        unsubscribed_at → flip to cancelled. No alert fired."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        conn.fetch.return_value = [_verifier_stream]
        conn.fetchrow.return_value = None  # _find_outflow_after → no match

        with patch("web.recurring.verifier.get_pool", AsyncMock(return_value=pool)):
            from web.recurring.verifier import verify_unsubscribed_streams

            counters = await verify_unsubscribed_streams()

        assert counters["checked"] == 1
        assert counters["cancelled"] == 1
        assert counters["alerts_fired"] == 0
        # _mark_cancelled UPDATE was issued.
        executes = [c.args[0] for c in conn.execute.call_args_list]
        assert any(
            "user_status" in sql and "'cancelled'" in sql for sql in executes
        ), "verifier must move row to user_status='cancelled'"

    @pytest.mark.asyncio
    async def test_charge_detected_fires_alert_and_leaves_state(
        self, _verifier_stream
    ):
        """If a fresh outflow with the same merchant exists, the verifier
        must NOT auto-revert to 'active'. It enqueues a P0 alert and
        leaves user_status = 'unsubscribed' so the user owns the call."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        conn.fetch.return_value = [_verifier_stream]
        # _find_outflow_after — outflow charge match.
        conn.fetchrow.return_value = {
            "id": 555,
            "date": date(2026, 4, 6),
            "amount_cents": 7929,
            "merchant_name": "AT&T",
            "description": "AT&T BILL PAY",
        }
        # _enqueue_charge_alert dedup lookup uses fetchval, not fetchrow.
        # None ⇒ no duplicate ⇒ we insert.
        conn.fetchval.return_value = None

        with patch("web.recurring.verifier.get_pool", AsyncMock(return_value=pool)):
            from web.recurring.verifier import verify_unsubscribed_streams

            counters = await verify_unsubscribed_streams()

        assert counters["checked"] == 1
        assert counters["cancelled"] == 0
        assert counters["alerts_fired"] == 1
        # Confirm an INSERT into notifications_queue happened with the
        # expected type.
        executes = [c.args[0] for c in conn.execute.call_args_list]
        inserted = any(
            "INSERT INTO notifications_queue" in sql for sql in executes
        )
        assert inserted, "verifier must enqueue the P0 alert"
        # And the row was NOT moved to cancelled.
        assert not any(
            "'cancelled'" in sql for sql in executes
        )

    @pytest.mark.asyncio
    async def test_charge_with_existing_dedup_skips_alert(
        self, _verifier_stream
    ):
        """If the alert is already queued (dedup key match within the
        7-day window), the verifier must NOT fire a duplicate. The
        ``alerts_skipped_dedup`` counter exists for telemetry."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        conn.fetch.return_value = [_verifier_stream]
        # outflow match
        conn.fetchrow.return_value = {
            "id": 555,
            "date": date(2026, 4, 6),
            "amount_cents": 7929,
            "merchant_name": "AT&T",
            "description": "",
        }
        # _enqueue_charge_alert dedup lookup found an existing row.
        conn.fetchval.return_value = 123

        with patch("web.recurring.verifier.get_pool", AsyncMock(return_value=pool)):
            from web.recurring.verifier import verify_unsubscribed_streams

            counters = await verify_unsubscribed_streams()

        assert counters["alerts_fired"] == 0
        assert counters["alerts_skipped_dedup"] == 1
        # No fresh INSERT into notifications_queue this round.
        executes = [c.args[0] for c in conn.execute.call_args_list]
        assert not any(
            "INSERT INTO notifications_queue" in sql for sql in executes
        )

    @pytest.mark.asyncio
    async def test_refund_does_not_trigger_alert(self, _verifier_stream):
        """A pro-rated refund (amount < 0 in our sign convention) after
        cancellation is a POSITIVE signal — the merchant honoured the
        cancel. The verifier's outflow query already filters
        ``amount_cents > 0`` so a refund-only row never matches, and the
        stream flips to cancelled normally."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)

        conn.fetch.return_value = [_verifier_stream]
        # No outflow match (refunds are filtered out at the SQL level).
        conn.fetchrow.return_value = None

        with patch("web.recurring.verifier.get_pool", AsyncMock(return_value=pool)):
            from web.recurring.verifier import verify_unsubscribed_streams

            counters = await verify_unsubscribed_streams()

        assert counters["cancelled"] == 1
        assert counters["alerts_fired"] == 0

    @pytest.mark.asyncio
    async def test_no_pending_streams(self):
        """Verifier with an empty input set is a clean no-op."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetch.return_value = []

        with patch("web.recurring.verifier.get_pool", AsyncMock(return_value=pool)):
            from web.recurring.verifier import verify_unsubscribed_streams

            counters = await verify_unsubscribed_streams()

        assert counters == {
            "checked": 0,
            "cancelled": 0,
            "alerts_fired": 0,
            "alerts_skipped_dedup": 0,
        }


# ---------------------------------------------------------------------------
# Notification builder
# ---------------------------------------------------------------------------


class TestUnsubscribeChargeRenderer:
    def test_renderer_returns_text_and_buttons(self):
        from web.notifications.builders import render_event

        text, keyboard = render_event(
            {
                "type": "unsubscribe_charge_detected",
                "payload": {
                    "stream_id": 99,
                    "name": "AT&T",
                    "amount_cents": 7929,
                    "currency": "USD",
                    "charge_date": "2026-04-06",
                    "unsubscribed_at": "2026-03-20T10:00:00+00:00",
                },
            }
        )
        assert "AT&T" in text
        assert "$79.29" in text
        assert "2026-04-06" in text
        # Two action buttons in one row: reactivate + cancel.
        assert len(keyboard) == 1
        labels = [btn[0] for btn in keyboard[0]]
        assert any("Reactivate" in lbl for lbl in labels)
        assert any("cancelled" in lbl.lower() for lbl in labels)

    def test_renderer_missing_stream_id_drops_buttons(self):
        """Without a stream_id the buttons would have no target. Better
        to render a text-only message than a button that 500s on click."""
        from web.notifications.builders import render_event

        text, keyboard = render_event(
            {
                "type": "unsubscribe_charge_detected",
                "payload": {
                    "name": "Netflix",
                    "amount_cents": 1599,
                    "charge_date": "2026-04-06",
                },
            }
        )
        assert "Netflix" in text
        assert keyboard == []
