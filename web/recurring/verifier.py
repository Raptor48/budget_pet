"""
Recurring-stream unsubscribe verifier.

Resolves the ``user_status = 'unsubscribed'`` state into one of two outcomes:

* **Confirmed cancelled** — Plaid has not posted a new outflow charge for
  the same merchant since the user clicked "unsubscribe", or Plaid itself
  flipped the stream to ``is_active = FALSE`` / ``status = TOMBSTONED``.
  The verifier moves the row to ``user_status = 'cancelled'`` and stamps
  ``cancelled_at``.

* **Charge detected** — Plaid posted a new outflow with this merchant
  *after* the unsubscribe timestamp. The verifier leaves the row in
  ``unsubscribed`` state and fires a P0 alert. The user sees "You marked
  AT&T as unsubscribed on Mar 20, but a $79.29 charge posted on Apr 6 —
  cancellation may not have gone through." From there they can decide to
  reactivate, dispute, or try cancelling at the merchant again.

We deliberately never auto-revert ``unsubscribed`` → ``active`` when a
charge is detected. The user already declared their intent; silently
flipping back would undo that. Asking them via P0 alert is the correct
escalation.

Cadences that auto-flip: ``WEEKLY``, ``BIWEEKLY``, ``SEMI_MONTHLY``,
``MONTHLY``. ``ANNUALLY`` and ``UNKNOWN`` rows stay in ``unsubscribed``
until manually finalised or Plaid tombstones them — see
``_compute_unsubscribe_verify_after`` in repo.py for the rationale.

The verifier is scheduled by ``web.notifications.dispatcher.start_dispatcher``
to run once per day at the same cadence as the producer top-up. It is
idempotent: a stream that's already in ``cancelled`` won't be reprocessed,
and the P0 alert dedup key prevents duplicate pushes on the same stream
within 24 h.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from web.db import get_pool

logger = logging.getLogger(__name__)


# Notification type for the "charge came through after unsubscribe" alert.
# Renderer lives in ``web/notifications/builders.py``.
ALERT_TYPE_UNSUBSCRIBE_CHARGE = "unsubscribe_charge_detected"


async def _list_due_streams(conn) -> List[Dict[str, Any]]:
    """Streams in ``unsubscribed`` state whose verify window has elapsed.

    ``unsubscribe_verify_after IS NULL`` means we never computed a deadline
    (ANNUALLY / UNKNOWN cadences) — we skip these here; they stay in
    ``unsubscribed`` for the user to finalise manually. The Plaid-side
    tombstone path below still applies — if Plaid kills the stream, we
    move it regardless of cadence.
    """
    rows = await conn.fetch(
        """
        SELECT rs.id,
               rs.account_id,
               rs.plaid_stream_id,
               rs.merchant_name,
               rs.description,
               rs.frequency,
               rs.last_date,
               rs.last_amount_cents,
               rs.average_amount_cents,
               rs.currency,
               rs.is_active,
               rs.status                 AS plaid_status,
               rs.unsubscribed_at,
               rs.unsubscribed_charge_alerted_at,
               a.user_id                 AS owner_user_id
        FROM recurring_streams rs
        LEFT JOIN accounts a ON a.id = rs.account_id
        WHERE rs.user_status = 'unsubscribed'
          AND (
                -- Auto-verifiable cadences hit their deadline …
                (rs.unsubscribe_verify_after IS NOT NULL
                 AND rs.unsubscribe_verify_after <= NOW())
                -- … or Plaid itself declared the stream dead.
                OR rs.is_active = FALSE
                OR UPPER(COALESCE(rs.status, '')) = 'TOMBSTONED'
              )
        """
    )
    return [dict(r) for r in rows]


async def _find_outflow_after(
    conn,
    *,
    account_id: Optional[int],
    merchant_name: Optional[str],
    since: datetime,
) -> Optional[Dict[str, Any]]:
    """Return the most recent outflow transaction matching the stream's
    merchant on or after ``since``, or ``None``.

    Belt-and-suspenders matching: same account_id (the user almost
    certainly stays at the same bank) PLUS a case-insensitive merchant
    name comparison. Plaid's ``recurring_streams`` table does not carry
    ``merchant_entity_id`` (the /recurring endpoint omits it), so the
    name match is the strongest signal we have. Refunds (``amount < 0``)
    are intentionally excluded — a pro-rated refund after cancellation is
    a *positive* signal of cancellation working, not a charge.
    """
    if not merchant_name or not merchant_name.strip():
        return None
    # No soft-delete on ``transactions`` in v2 — ``delete_removed_transactions``
    # hard-deletes Plaid removals on the next sync, so a stale row never
    # surfaces here.
    row = await conn.fetchrow(
        """
        SELECT t.id, t.date, t.amount_cents, t.merchant_name, t.name
        FROM transactions t
        WHERE t.account_id = $1
          AND t.amount_cents > 0
          AND t.date >= $2::date
          AND LOWER(NULLIF(TRIM(t.merchant_name), '')) = LOWER(TRIM($3))
        ORDER BY t.date DESC, t.id DESC
        LIMIT 1
        """,
        account_id,
        since.date(),
        merchant_name,
    )
    return dict(row) if row else None


async def _enqueue_charge_alert(
    conn,
    stream: Dict[str, Any],
    charge: Dict[str, Any],
) -> bool:
    """Enqueue the "charge after unsubscribe" P0 alert if not already
    queued. Returns ``True`` if a new row was inserted, ``False`` on dedup.

    Uses ``notifications_queue`` directly (not ``enqueue_notification``)
    so we can write inside the verifier's transaction and avoid a
    re-entrant pool acquire. The dedup key matches the producer pattern
    so the daily/hourly producer top-up will not double-fire either.
    """
    owner_uid = stream.get("owner_user_id")
    if owner_uid is None:
        # Stream sits on a shared / unlinked account — we don't have a
        # user to ping. Skip the alert; the row still gets state-resolved
        # below.
        return False
    dedup_key = f"unsubscribe_charge_detected:{int(stream['id'])}:{charge['date']}"
    payload = {
        "stream_id": int(stream["id"]),
        "name": stream.get("merchant_name") or stream.get("description") or "Subscription",
        "amount_cents": int(charge.get("amount_cents") or 0),
        "currency": stream.get("currency") or "USD",
        "charge_date": str(charge["date"]),
        "unsubscribed_at": (
            stream["unsubscribed_at"].isoformat()
            if isinstance(stream.get("unsubscribed_at"), datetime)
            else stream.get("unsubscribed_at")
        ),
    }
    existing = await conn.fetchval(
        """
        SELECT id FROM notifications_queue
        WHERE user_id = $1
          AND type    = $2
          AND dedup_key = $3
          AND failed_at IS NULL
          AND created_at > NOW() - INTERVAL '7 days'
        """,
        int(owner_uid),
        ALERT_TYPE_UNSUBSCRIBE_CHARGE,
        dedup_key,
    )
    if existing is not None:
        return False
    await conn.execute(
        """
        INSERT INTO notifications_queue
            (user_id, type, priority, payload, dedup_key, scheduled_at)
        VALUES ($1, $2, 'P0', $3::jsonb, $4, NOW())
        """,
        int(owner_uid),
        ALERT_TYPE_UNSUBSCRIBE_CHARGE,
        json.dumps(payload, default=str),
        dedup_key,
    )
    await conn.execute(
        """
        UPDATE recurring_streams
           SET unsubscribed_charge_alerted_at = NOW()
         WHERE id = $1
        """,
        int(stream["id"]),
    )
    return True


async def _mark_cancelled(conn, stream_id: int) -> None:
    """Verifier-side terminal move: ``unsubscribed`` → ``cancelled``.

    Stamps ``cancelled_at`` and clears verifier metadata. Does NOT clear
    ``unsubscribed_at`` — we keep it as an audit breadcrumb so we can
    show "You unsubscribed Mar 20, confirmed cancelled Apr 13" in the UI
    history if we ever surface it.
    """
    await conn.execute(
        """
        UPDATE recurring_streams
           SET user_status              = 'cancelled',
               cancelled_at             = NOW(),
               unsubscribe_verify_after = NULL
         WHERE id = $1
           AND user_status = 'unsubscribed'
        """,
        int(stream_id),
    )


async def verify_unsubscribed_streams() -> Dict[str, int]:
    """One pass of the verifier. Returns counters for telemetry / tests.

    Counter semantics:
      * ``checked``       — streams whose verify window had elapsed.
      * ``cancelled``     — moved to ``user_status = 'cancelled'``.
      * ``alerts_fired``  — P0 "charge detected" notifications enqueued.
      * ``alerts_skipped_dedup`` — alert was already in flight; no-op.

    Idempotent: re-running mid-window is safe. The dedup key on the
    notification + the ``WHERE user_status = 'unsubscribed'`` guard on
    the cancel UPDATE both protect against double-action.
    """
    pool = await get_pool()
    counters = {
        "checked": 0,
        "cancelled": 0,
        "alerts_fired": 0,
        "alerts_skipped_dedup": 0,
    }
    async with pool.acquire() as conn:
        streams = await _list_due_streams(conn)
        for s in streams:
            counters["checked"] += 1
            since = s.get("unsubscribed_at") or datetime.now(timezone.utc)
            if not isinstance(since, datetime):
                # asyncpg always returns TIMESTAMPTZ as datetime; defensive
                # fallback so a partial test fixture doesn't crash here.
                since = datetime.now(timezone.utc)
            charge = await _find_outflow_after(
                conn,
                account_id=s.get("account_id"),
                merchant_name=s.get("merchant_name"),
                since=since,
            )
            if charge:
                fired = await _enqueue_charge_alert(conn, s, charge)
                if fired:
                    counters["alerts_fired"] += 1
                else:
                    counters["alerts_skipped_dedup"] += 1
                # Don't flip the user_status. The user declared the intent;
                # the charge is a fact that contradicts the intent — they
                # decide what to do with it.
                continue
            # No outflow since unsubscribe → confirmed cancelled.
            await _mark_cancelled(conn, int(s["id"]))
            counters["cancelled"] += 1
    logger.info(
        "Unsubscribe verifier: checked=%d cancelled=%d alerts=%d dedup=%d",
        counters["checked"],
        counters["cancelled"],
        counters["alerts_fired"],
        counters["alerts_skipped_dedup"],
    )
    return counters
