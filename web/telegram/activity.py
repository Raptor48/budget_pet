"""
bot_activity_log writes — surfaced in the frontend Bot → Activity tab so
the user doesn't have to open Railway logs to see if the bot is alive.

Design:
* The helper is a fire-and-forget writer. We swallow + log any exception
  so a misbehaving log statement can never break the calling handler.
* All writes go through the shared asyncpg pool with a tight 5-second
  guard — if the DB is slow we'd rather lose a log line than block a
  user-facing action.
* Payload is opaque JSON, capped at ~4 KB to keep rows small. Errors get
  the last 4 KB of the traceback (head + tail) so most exceptions remain
  legible without bloating storage.

Kinds (canonical strings — keep stable, the frontend filters on these):

* ``incoming.command``     — "/start", "/menu", "/balance"…
* ``incoming.text``        — free-text cash entry parse
* ``incoming.photo``       — receipt photo upload
* ``incoming.callback``    — inline button tap (menu drill, mood, tea, chore done)
* ``outgoing.push``        — message sent FROM dispatcher (P0/P1/P2)
* ``ocr.success`` / ``ocr.failure``
* ``error``                — uncaught exception in any handler
* ``link.attached`` / ``link.detached``
"""
from __future__ import annotations

import asyncio
import json
import logging
import traceback
from typing import Any, Dict, Optional

from web.db import get_pool

logger = logging.getLogger(__name__)

_PAYLOAD_LIMIT_BYTES = 4096
_ERROR_LIMIT_CHARS = 4000


def _truncate_payload(payload: Optional[Dict[str, Any]]) -> str:
    if not payload:
        return "{}"
    blob = json.dumps(payload, default=str, ensure_ascii=False)
    if len(blob.encode("utf-8")) <= _PAYLOAD_LIMIT_BYTES:
        return blob
    # Fall back to a placeholder so the row still inserts and the user
    # sees that something happened.
    return json.dumps(
        {
            "_truncated": True,
            "_size_bytes": len(blob.encode("utf-8")),
            "_keys": list(payload.keys())[:20],
        }
    )


def _truncate_error(err: Optional[BaseException]) -> Optional[str]:
    if err is None:
        return None
    tb = "".join(traceback.format_exception(type(err), err, err.__traceback__))
    if len(tb) <= _ERROR_LIMIT_CHARS:
        return tb
    half = _ERROR_LIMIT_CHARS // 2 - 32
    return tb[:half] + "\n…[truncated]…\n" + tb[-half:]


async def log_bot_activity(
    *,
    kind: str,
    summary: str,
    user_id: Optional[int] = None,
    chat_id: Optional[int] = None,
    severity: str = "info",
    payload: Optional[Dict[str, Any]] = None,
    error: Optional[BaseException] = None,
) -> None:
    """Insert a row into bot_activity_log. Never raises.

    ``user_id`` / ``chat_id`` are best-effort — pass whatever you have at
    the call site. Errors should pass ``severity='error'`` and the
    exception via ``error`` so the traceback gets stored.
    """
    if severity not in ("info", "warn", "error"):
        severity = "info"
    payload_json = _truncate_payload(payload)
    error_text = _truncate_error(error)

    async def _do():
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO bot_activity_log
                        (user_id, chat_id, kind, severity, summary, payload, error)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                    """,
                    user_id,
                    chat_id,
                    kind,
                    severity,
                    summary[:300],
                    payload_json,
                    error_text,
                )
        except Exception:  # noqa: BLE001 — logging must never break callers
            logger.exception("bot_activity_log INSERT failed")

    try:
        await asyncio.wait_for(_do(), timeout=5)
    except asyncio.TimeoutError:
        logger.warning(
            "bot_activity_log timed out (kind=%s, summary=%s)", kind, summary[:80]
        )
    except Exception:
        logger.exception("bot_activity_log unexpected failure")


async def list_activity(
    *,
    limit: int = 100,
    severity: Optional[str] = None,
    kind_prefix: Optional[str] = None,
    user_id: Optional[int] = None,
) -> list[Dict[str, Any]]:
    """Read recent rows. Used by GET /api/bot/activity.

    The row dict includes ``username`` when the originating user is known,
    so the cross-user (owner) view can label rows without a per-row
    follow-up lookup.
    """
    pool = await get_pool()
    sql = (
        "SELECT b.id, b.user_id, b.chat_id, b.kind, b.severity, b.summary, "
        "b.payload, b.error, b.created_at, u.username "
        "FROM bot_activity_log b "
        "LEFT JOIN users u ON u.id = b.user_id "
        "WHERE 1=1"
    )
    args: list[Any] = []
    if severity:
        args.append(severity)
        sql += f" AND b.severity = ${len(args)}"
    if kind_prefix:
        args.append(kind_prefix + "%")
        sql += f" AND b.kind LIKE ${len(args)}"
    if user_id is not None:
        args.append(user_id)
        sql += f" AND (b.user_id = ${len(args)} OR b.user_id IS NULL)"
    args.append(int(limit))
    sql += f" ORDER BY b.id DESC LIMIT ${len(args)}"
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


async def prune_activity(*, older_than_days: int = 30) -> int:
    """Delete rows older than ``older_than_days``. Returns rows deleted."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            f"DELETE FROM bot_activity_log "
            f"WHERE created_at < NOW() - make_interval(days => $1)",
            int(older_than_days),
        )
    # asyncpg returns "DELETE N" — extract count for telemetry.
    try:
        return int(res.split()[-1])
    except Exception:
        return 0
