"""
Notification queue helpers.

Every alert producer calls :func:`enqueue_notification` with a priority
(P0/P1/P2) and an optional ``dedup_key``. The dispatcher drains the queue
once per minute, batching P1 events into a single morning brief and bundling
P2 into the weekly brief.

Priority semantics:
    P0 — must reach the user immediately, even during quiet hours
         (Plaid reauth, suspected duplicate charge, etc.).
    P1 — bundled into the per-user "morning brief" at the time configured
         in ``couple_settings.morning_brief_local`` (default 09:00).
    P2 — bundled into the Sunday brief when ``sunday_brief_enabled``;
         otherwise rolled up into the next morning brief.

Dedup:
    ``dedup_key`` is unique per user/type within a 24-hour window. Re-enqueue
    with the same key is a no-op so producers can fire-and-forget without
    worrying about duplicate alerts (e.g. running the budget-threshold check
    every hour).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from web.db import get_pool

logger = logging.getLogger(__name__)


def dedup_key_for(*parts: Any) -> str:
    """Build a stable dedup key from heterogeneous parts (str/int/date)."""
    return ":".join(str(p) for p in parts if p is not None)


async def enqueue_notification(
    *,
    user_id: int,
    type: str,
    payload: Dict[str, Any],
    priority: str = "P1",
    dedup_key: Optional[str] = None,
    scheduled_at: Optional[datetime] = None,
    dedup_window_hours: int = 24,
) -> Optional[int]:
    """Insert a row unless a recent matching row already exists.

    Returns the new row id, or ``None`` if the alert was deduped.
    """
    if priority not in ("P0", "P1", "P2"):
        raise ValueError(f"Invalid priority: {priority}")
    pool = await get_pool()
    sched = scheduled_at or datetime.now(timezone.utc)
    payload_json = json.dumps(payload, default=str)
    async with pool.acquire() as conn:
        if dedup_key:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=dedup_window_hours)
            existing = await conn.fetchval(
                """
                SELECT id FROM notifications_queue
                WHERE user_id = $1 AND type = $2 AND dedup_key = $3
                  AND created_at > $4
                  AND failed_at IS NULL
                """,
                user_id,
                type,
                dedup_key,
                cutoff,
            )
            if existing is not None:
                logger.debug(
                    "Dedup hit for user=%s type=%s key=%s — skipping",
                    user_id,
                    type,
                    dedup_key,
                )
                return None
        new_id = await conn.fetchval(
            """
            INSERT INTO notifications_queue
                (user_id, type, priority, payload, dedup_key, scheduled_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6)
            RETURNING id
            """,
            user_id,
            type,
            priority,
            payload_json,
            dedup_key,
            sched,
        )
    logger.info(
        "Enqueued notification id=%s user=%s type=%s priority=%s",
        new_id,
        user_id,
        type,
        priority,
    )
    return new_id


async def list_pending_for_user(
    user_id: int,
    *,
    priorities: Optional[List[str]] = None,
    only_due: bool = True,
    bundle_into_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Pull pending rows. Use ``bundle_into_id=None`` (default) to fetch
    rows that have not yet been folded into a parent brief.

    Honours the ``not_before`` embargo so a row that just got hit by a
    Telegram ``RetryAfter`` waits out its cooldown before becoming
    visible to the dispatcher again.
    """
    pool = await get_pool()
    sql = (
        "SELECT id, type, priority, payload, dedup_key, scheduled_at, created_at "
        "FROM notifications_queue "
        "WHERE user_id = $1 AND sent_at IS NULL AND failed_at IS NULL "
        "AND bundled_into_id IS NULL "
        "AND (not_before IS NULL OR not_before <= NOW())"
    )
    args: List[Any] = [user_id]
    if priorities:
        args.append(priorities)
        sql += f" AND priority = ANY(${len(args)})"
    if only_due:
        args.append(datetime.now(timezone.utc))
        sql += f" AND scheduled_at <= ${len(args)}"
    sql += " ORDER BY priority, scheduled_at"
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("payload"), str):
            try:
                d["payload"] = json.loads(d["payload"])
            except Exception:
                d["payload"] = {}
        out.append(d)
    return out


async def mark_sent(ids: List[int]) -> None:
    if not ids:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE notifications_queue SET sent_at = NOW() WHERE id = ANY($1::bigint[])",
            ids,
        )


async def mark_failed(notif_id: int, error: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE notifications_queue SET failed_at = NOW(), error = $2 WHERE id = $1",
            notif_id,
            error,
        )


async def defer_until(notif_id: int, retry_after_seconds: int) -> None:
    """Telegram ``RetryAfter``: leave the row in the queue and stamp the
    ``not_before`` embargo so :func:`list_pending_for_user` skips it for
    ``retry_after_seconds`` before becoming eligible again.

    Pre-fix, ``RetryAfter`` was caught by the dispatcher's broad ``except``
    and the row was marked ``failed`` — silently dropping briefs whenever
    Telegram rate-limited us. ``not_before`` keeps the row alive without
    re-enqueueing on the next minute.
    """
    if retry_after_seconds <= 0:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE notifications_queue
               SET not_before = NOW() + ($2 || ' seconds')::interval
             WHERE id = $1
            """,
            notif_id,
            int(retry_after_seconds),
        )


async def defer_many_until(ids: List[int], retry_after_seconds: int) -> None:
    """Bulk variant of :func:`defer_until` for brief sends. Same semantics."""
    if not ids or retry_after_seconds <= 0:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE notifications_queue
               SET not_before = NOW() + ($2 || ' seconds')::interval
             WHERE id = ANY($1::bigint[])
            """,
            ids,
            int(retry_after_seconds),
        )


