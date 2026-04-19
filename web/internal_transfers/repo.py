"""DB operations for internal-transfer settings.

The list lives on the ``app_settings`` singleton (``internal_transfer_names``
column). A separate repository keeps the feature code cohesive and lets
tests mock a focused surface instead of the whole ``AppSettingsRepository``.
"""
from __future__ import annotations

import logging
from typing import List

import asyncpg

from web.db import get_pool

logger = logging.getLogger(__name__)


def _sanitize_names(raw: List[str]) -> List[str]:
    """Trim whitespace, drop empty entries, and dedupe case-insensitively
    while preserving the first user-typed casing (used for display)."""
    out: List[str] = []
    seen: set[str] = set()
    for name in raw:
        if not isinstance(name, str):
            continue
        clean = " ".join(name.split()).strip()
        if not clean:
            continue
        key = clean.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


class InternalTransferSettingsRepository:
    async def _pool(self) -> asyncpg.Pool:
        return await get_pool()

    async def get_names(self) -> List[str]:
        """Return the current list (verbatim). Empty when the DB is fresh or
        the column has not been seeded."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT internal_transfer_names FROM app_settings WHERE id = 1"
            )
        if not row:
            return []
        return list(row["internal_transfer_names"] or [])

    async def set_names(self, names: List[str]) -> List[str]:
        """Replace the list; sanitize first so we never persist whitespace-only
        or duplicate entries. The singleton row is created by the migration,
        so we only UPDATE here (the app_settings upsert in AppSettingsRepository
        handles the first-run insertion for us)."""
        sanitized = _sanitize_names(names)
        pool = await self._pool()
        async with pool.acquire() as conn:
            # Mirrors how `AppSettingsRepository.get()` seeds the singleton
            # row — safe to call even on a fresh DB.
            await conn.execute(
                """
                INSERT INTO app_settings (id, internal_transfer_names)
                VALUES (1, $1::text[])
                ON CONFLICT (id) DO UPDATE SET
                    internal_transfer_names = EXCLUDED.internal_transfer_names,
                    updated_at = NOW()
                """,
                sanitized,
            )
        return sanitized


_repo: InternalTransferSettingsRepository | None = None


def get_internal_transfer_settings_repo() -> InternalTransferSettingsRepository:
    global _repo
    if _repo is None:
        _repo = InternalTransferSettingsRepository()
    return _repo
