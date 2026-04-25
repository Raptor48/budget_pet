"""Persistence + cache layer for the Insights feed.

Responsibilities:

- ``recompute_and_store(viewer_user_id)`` runs the card builders, upserts
  each card into ``insights_cards`` on ``dedupe_key``, and prunes rows
  whose ``last_seen_at`` is older than ``card_prune_days`` (provided no
  user is still hanging on to their dismiss/snooze state for them).
- ``load_feed(viewer_user_id, include_hidden)`` returns the feed payload
  read from the DB, joined against ``insights_card_user_state`` for this
  viewer. Dismissed / still-snoozed cards are filtered out unless
  ``include_hidden`` is true, in which case they come back with a
  ``user_state`` block so the UI can offer "Unhide".
- ``set_card_state(user_id, dedupe_key, ...)`` upserts dismissal/snooze
  rows.

Caching: ``build_insights_feed`` is expensive (hits multiple repos), so
the API layer calls :func:`get_feed_cached` which re-runs the builders
at most once every ``cache_ttl_seconds``. The cache is per-viewer so
privacy filters are honored.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from web.db import get_pool

from .config import InsightsConfig, load_config
from .feed import build_insights_feed

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-process cache for the feed (small, per-viewer).
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    generated_at: datetime
    payload: Dict[str, Any]


_CACHE: Dict[Optional[int], _CacheEntry] = {}
_CACHE_LOCK = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Upsert / load primitives
# ---------------------------------------------------------------------------


async def _upsert_cards(cards: List[Dict[str, Any]]) -> None:
    """Upsert each card by ``dedupe_key``. ``first_seen_at`` is preserved
    on conflict; ``last_seen_at`` refreshes to NOW() so pruning won't
    delete an actively-surfacing card."""
    if not cards:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        for c in cards:
            dedupe_key = c.get("dedupe_key")
            if not dedupe_key:
                continue
            await conn.execute(
                """
                INSERT INTO insights_cards (
                    dedupe_key, type, severity, title, summary, detail,
                    action_url, action_label, payload, last_seen_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, NOW())
                ON CONFLICT (dedupe_key) DO UPDATE SET
                    type = EXCLUDED.type,
                    severity = EXCLUDED.severity,
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    detail = EXCLUDED.detail,
                    action_url = EXCLUDED.action_url,
                    action_label = EXCLUDED.action_label,
                    payload = EXCLUDED.payload,
                    last_seen_at = NOW()
                """,
                dedupe_key,
                c.get("type"),
                c.get("severity"),
                c.get("title"),
                c.get("summary"),
                c.get("detail"),
                c.get("action_url"),
                c.get("action_label"),
                json.dumps(c.get("payload") or {}),
            )


async def _prune_stale(cfg: InsightsConfig) -> None:
    """Drop cards whose ``last_seen_at`` is older than the configured window
    *and* have no user state referencing them. Dismiss/snooze rows keep a
    card alive in the table so the user's hide decision persists across
    re-surfacing."""
    pool = await get_pool()
    cutoff = _now() - timedelta(days=cfg.card_prune_days)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            DELETE FROM insights_cards c
            WHERE c.last_seen_at < $1
              AND NOT EXISTS (
                  SELECT 1 FROM insights_card_user_state s
                  WHERE s.dedupe_key = c.dedupe_key
              )
            """,
            cutoff,
        )


async def recompute_and_store(
    viewer_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the raw feed, upsert each card into the store, prune stale,
    and return the freshly-built payload."""
    cfg = await load_config()
    payload = await build_insights_feed(viewer_user_id=viewer_user_id)
    try:
        await _upsert_cards(payload.get("cards") or [])
        await _prune_stale(cfg)
    except Exception as exc:
        # Store layer is best-effort: failing to persist must not break
        # the feed for the user (e.g. migration hasn't run yet on a new
        # deploy). Log and return the in-memory payload.
        logger.warning("insights store upsert/prune failed: %s", exc)
    return payload


async def _load_user_state(
    viewer_user_id: Optional[int],
    dedupe_keys: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Return ``{dedupe_key: {dismissed_at, snoozed_until}}`` for ``viewer_user_id``.

    Empty dict when ``viewer_user_id is None`` (anonymous/no-auth contexts).
    """
    if not viewer_user_id or not dedupe_keys:
        return {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT dedupe_key, dismissed_at, snoozed_until
            FROM insights_card_user_state
            WHERE user_id = $1 AND dedupe_key = ANY($2::text[])
            """,
            int(viewer_user_id),
            list(dedupe_keys),
        )
    return {
        r["dedupe_key"]: {
            "dismissed_at": r["dismissed_at"],
            "snoozed_until": r["snoozed_until"],
        }
        for r in rows
    }


async def _load_insights_last_viewed_at(
    viewer_user_id: Optional[int],
) -> Optional[datetime]:
    if not viewer_user_id:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT insights_last_viewed_at FROM user_preferences WHERE user_id = $1",
            int(viewer_user_id),
        )


async def _load_first_seen_at(
    dedupe_keys: List[str],
) -> Dict[str, datetime]:
    if not dedupe_keys:
        return {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT dedupe_key, first_seen_at FROM insights_cards WHERE dedupe_key = ANY($1::text[])",
            list(dedupe_keys),
        )
    return {r["dedupe_key"]: r["first_seen_at"] for r in rows}


def _user_state_for_response(state: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize timestamps to ISO strings for JSON serialization."""
    dismissed = state.get("dismissed_at")
    snoozed = state.get("snoozed_until")
    return {
        "dismissed": dismissed is not None,
        "dismissed_at": dismissed.isoformat() if dismissed else None,
        "snoozed_until": snoozed.isoformat() if snoozed else None,
    }


def _is_hidden(state: Dict[str, Any], now: datetime) -> bool:
    if state.get("dismissed_at") is not None:
        return True
    snoozed = state.get("snoozed_until")
    if snoozed and snoozed > now:
        return True
    return False


async def load_feed(
    viewer_user_id: Optional[int],
    *,
    include_hidden: bool = False,
) -> Dict[str, Any]:
    """Return the feed from in-memory + DB state.

    Steps:
    1. Ensure the store is fresh (``get_feed_cached`` must have called
       :func:`recompute_and_store` for us earlier).
    2. Overlay ``user_state`` (dismissed/snoozed) per card.
    3. Compute ``new_count`` as cards whose ``first_seen_at >
       user_preferences.insights_last_viewed_at``.
    """
    # We assume the caller (API layer) already populated the in-memory cache.
    entry = _CACHE.get(viewer_user_id)
    if entry is None:
        payload = await recompute_and_store(viewer_user_id=viewer_user_id)
    else:
        payload = entry.payload

    cards: List[Dict[str, Any]] = list(payload.get("cards") or [])
    dedupe_keys = [c["dedupe_key"] for c in cards if c.get("dedupe_key")]
    user_states = await _load_user_state(viewer_user_id, dedupe_keys)
    first_seen = await _load_first_seen_at(dedupe_keys)
    last_viewed_at = await _load_insights_last_viewed_at(viewer_user_id)
    now = _now()

    out_cards: List[Dict[str, Any]] = []
    new_count = 0
    actionable_count = 0
    for c in cards:
        key = c.get("dedupe_key") or ""
        state = user_states.get(key, {})
        hidden = _is_hidden(state, now)
        if hidden and not include_hidden:
            continue
        c2 = dict(c)
        c2["user_state"] = _user_state_for_response(state)
        # new_count counts only non-hidden cards first seen after last visit.
        first_ts = first_seen.get(key)
        is_new = (
            first_ts is not None
            and (last_viewed_at is None or first_ts > last_viewed_at)
        )
        c2["is_new"] = bool(is_new)
        if not hidden and c.get("severity") == "warn":
            actionable_count += 1
        if not hidden and is_new:
            new_count += 1
        out_cards.append(c2)

    return {
        "cards": out_cards,
        "actionable_count": actionable_count,
        "new_count": new_count,
    }


async def get_feed_cached(
    viewer_user_id: Optional[int],
    *,
    include_hidden: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """Main API entry-point. Recomputes if stale, else serves from cache.

    The 5-minute default TTL is set via ``app_settings.insights_config``.
    """
    cfg = await load_config()
    ttl = timedelta(seconds=cfg.cache_ttl_seconds)
    async with _CACHE_LOCK:
        entry = _CACHE.get(viewer_user_id)
        stale = force or entry is None or (_now() - entry.generated_at) > ttl
        if stale:
            payload = await recompute_and_store(viewer_user_id=viewer_user_id)
            _CACHE[viewer_user_id] = _CacheEntry(generated_at=_now(), payload=payload)
    return await load_feed(viewer_user_id, include_hidden=include_hidden)


def invalidate_cache(viewer_user_id: Optional[int] = None) -> None:
    """Drop cached payloads. ``None`` drops everything."""
    if viewer_user_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(viewer_user_id, None)


# ---------------------------------------------------------------------------
# User-state mutators (dismiss / snooze / unhide)
# ---------------------------------------------------------------------------


async def _card_exists(dedupe_key: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT 1 FROM insights_cards WHERE dedupe_key = $1",
            dedupe_key,
        )
    return bool(val)


async def dismiss_card(user_id: int, dedupe_key: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO insights_card_user_state (user_id, dedupe_key, dismissed_at, updated_at)
            VALUES ($1, $2, NOW(), NOW())
            ON CONFLICT (user_id, dedupe_key) DO UPDATE SET
                dismissed_at = NOW(),
                updated_at = NOW()
            """,
            int(user_id),
            dedupe_key,
        )
    invalidate_cache(user_id)


async def snooze_card(user_id: int, dedupe_key: str, until: datetime) -> datetime:
    """Clamp ``until`` to ``snooze_max_days`` in the future and store it."""
    cfg = await load_config()
    cap = _now() + timedelta(days=cfg.snooze_max_days)
    if until > cap:
        until = cap
    if until <= _now():
        raise ValueError("snooze_until must be in the future")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO insights_card_user_state (user_id, dedupe_key, snoozed_until, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (user_id, dedupe_key) DO UPDATE SET
                snoozed_until = EXCLUDED.snoozed_until,
                updated_at = NOW()
            """,
            int(user_id),
            dedupe_key,
            until,
        )
    invalidate_cache(user_id)
    return until


async def unhide_card(user_id: int, dedupe_key: str) -> None:
    """Clear both ``dismissed_at`` and ``snoozed_until`` for this user/card."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE insights_card_user_state
            SET dismissed_at = NULL,
                snoozed_until = NULL,
                updated_at = NOW()
            WHERE user_id = $1 AND dedupe_key = $2
            """,
            int(user_id),
            dedupe_key,
        )
    invalidate_cache(user_id)


__all__ = [
    "DEFAULTS_CACHE_KEY",
    "dismiss_card",
    "get_feed_cached",
    "invalidate_cache",
    "load_feed",
    "recompute_and_store",
    "snooze_card",
    "unhide_card",
]


# ---------------------------------------------------------------------------
# Test hooks
# ---------------------------------------------------------------------------

# Re-exported so tests can reset cache state without reaching into module internals.
DEFAULTS_CACHE_KEY = None  # sentinel: "no viewer" bucket
