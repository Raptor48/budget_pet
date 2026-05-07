"""
Notification orchestration package.

* ``queue``      — enqueue + dedup helpers (used by every alert producer)
* ``dispatcher`` — APScheduler-driven drain that respects priority,
                   quiet hours, batching windows, and per-user opt-ins
* ``builders``   — turn raw events into Telegram messages (sectioned briefs)
"""
from .queue import (
    enqueue_notification,
    dedup_key_for,
    list_pending_for_user,
    mark_sent,
    mark_failed,
)

__all__ = [
    "enqueue_notification",
    "dedup_key_for",
    "list_pending_for_user",
    "mark_sent",
    "mark_failed",
]
