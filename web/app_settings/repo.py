"""
Repository for the singleton `app_settings` row.

The row is a single-row table (enforced by a PK=1 CHECK), so every read upserts
defaults and every write updates the same row in place.
"""
import logging
from typing import Any, Dict, Optional

from .models import AUTOSYNC_FREQUENCIES

logger = logging.getLogger(__name__)


DEFAULTS: Dict[str, Any] = {
    "autosync_frequency": "daily",
    "autosync_hour_utc": 3,
    "autosync_minute_utc": 0,
    "webhooks_enabled": True,
    "bot_activity_auto_prune_enabled": True,
    "audit_log_auto_prune_enabled": False,
}


class AppSettingsRepository:
    async def _pool(self):
        from web.db import get_pool
        return await get_pool()

    async def get(self) -> Dict[str, Any]:
        """Return the singleton settings row, inserting defaults if missing."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO app_settings
                    (id, autosync_frequency, autosync_hour_utc, autosync_minute_utc, webhooks_enabled)
                VALUES (1, $1, $2, $3, $4)
                ON CONFLICT (id) DO NOTHING
                """,
                DEFAULTS["autosync_frequency"],
                DEFAULTS["autosync_hour_utc"],
                DEFAULTS["autosync_minute_utc"],
                DEFAULTS["webhooks_enabled"],
            )
            row = await conn.fetchrow(
                """
                SELECT s.autosync_frequency, s.autosync_hour_utc, s.autosync_minute_utc,
                       s.webhooks_enabled,
                       s.bot_activity_auto_prune_enabled,
                       s.audit_log_auto_prune_enabled,
                       s.updated_at, s.updated_by,
                       u.username AS updated_by_username
                FROM app_settings s
                LEFT JOIN users u ON u.id = s.updated_by
                WHERE s.id = 1
                """
            )
        return dict(row)

    async def update(
        self,
        *,
        frequency: Optional[str] = None,
        hour_utc: Optional[int] = None,
        minute_utc: Optional[int] = None,
        webhooks_enabled: Optional[bool] = None,
        bot_activity_auto_prune_enabled: Optional[bool] = None,
        audit_log_auto_prune_enabled: Optional[bool] = None,
        updated_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Patch the singleton row. Returns the fresh row."""
        if all(
            v is None
            for v in (
                frequency,
                hour_utc,
                minute_utc,
                webhooks_enabled,
                bot_activity_auto_prune_enabled,
                audit_log_auto_prune_enabled,
            )
        ):
            return await self.get()

        current = await self.get()
        new_frequency = (
            current["autosync_frequency"] if frequency is None else str(frequency)
        )
        new_hour = current["autosync_hour_utc"] if hour_utc is None else int(hour_utc)
        new_minute = current["autosync_minute_utc"] if minute_utc is None else int(minute_utc)
        new_webhooks = (
            current["webhooks_enabled"] if webhooks_enabled is None else bool(webhooks_enabled)
        )
        new_bot_prune = (
            current.get("bot_activity_auto_prune_enabled", True)
            if bot_activity_auto_prune_enabled is None
            else bool(bot_activity_auto_prune_enabled)
        )
        new_audit_prune = (
            current.get("audit_log_auto_prune_enabled", False)
            if audit_log_auto_prune_enabled is None
            else bool(audit_log_auto_prune_enabled)
        )

        if new_frequency not in AUTOSYNC_FREQUENCIES:
            raise ValueError(
                f"frequency must be one of {AUTOSYNC_FREQUENCIES}, got {new_frequency!r}"
            )
        if not (0 <= new_hour <= 23):
            raise ValueError("hour_utc must be between 0 and 23")
        if not (0 <= new_minute <= 59):
            raise ValueError("minute_utc must be between 0 and 59")

        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE app_settings
                SET autosync_frequency = $1,
                    autosync_hour_utc = $2,
                    autosync_minute_utc = $3,
                    webhooks_enabled = $4,
                    bot_activity_auto_prune_enabled = $5,
                    audit_log_auto_prune_enabled = $6,
                    updated_at = NOW(),
                    updated_by = $7
                WHERE id = 1
                """,
                new_frequency,
                new_hour,
                new_minute,
                new_webhooks,
                new_bot_prune,
                new_audit_prune,
                updated_by,
            )
        return await self.get()


_repo: Optional[AppSettingsRepository] = None


def get_app_settings_repo() -> AppSettingsRepository:
    global _repo
    if _repo is None:
        _repo = AppSettingsRepository()
    return _repo
