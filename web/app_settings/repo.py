"""Repository for app_settings — asyncpg. Stores a single row (id=1)."""
from typing import Any, Dict, Optional


DEFAULTS: Dict[str, Any] = {
    "autosync_enabled": True,
    "autosync_hour_utc": 3,
    "autosync_minute_utc": 0,
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
                INSERT INTO app_settings (id, autosync_enabled, autosync_hour_utc, autosync_minute_utc)
                VALUES (1, $1, $2, $3)
                ON CONFLICT (id) DO NOTHING
                """,
                DEFAULTS["autosync_enabled"],
                DEFAULTS["autosync_hour_utc"],
                DEFAULTS["autosync_minute_utc"],
            )
            row = await conn.fetchrow(
                """
                SELECT s.autosync_enabled, s.autosync_hour_utc, s.autosync_minute_utc,
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
        enabled: Optional[bool] = None,
        hour_utc: Optional[int] = None,
        minute_utc: Optional[int] = None,
        updated_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Patch the singleton row. Returns the fresh row."""
        if enabled is None and hour_utc is None and minute_utc is None:
            return await self.get()

        current = await self.get()
        new_enabled = current["autosync_enabled"] if enabled is None else bool(enabled)
        new_hour = current["autosync_hour_utc"] if hour_utc is None else int(hour_utc)
        new_minute = current["autosync_minute_utc"] if minute_utc is None else int(minute_utc)

        if not (0 <= new_hour <= 23):
            raise ValueError("hour_utc must be between 0 and 23")
        if not (0 <= new_minute <= 59):
            raise ValueError("minute_utc must be between 0 and 59")

        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE app_settings
                SET autosync_enabled = $1,
                    autosync_hour_utc = $2,
                    autosync_minute_utc = $3,
                    updated_at = NOW(),
                    updated_by = $4
                WHERE id = 1
                """,
                new_enabled,
                new_hour,
                new_minute,
                updated_by,
            )
        return await self.get()


_repo: Optional[AppSettingsRepository] = None


def get_app_settings_repo() -> AppSettingsRepository:
    global _repo
    if _repo is None:
        _repo = AppSettingsRepository()
    return _repo
