import logging
from typing import Any, Dict, List, Optional

from web.db import get_pool

logger = logging.getLogger(__name__)


class TagsRepository:
    async def _pool(self):
        return await get_pool()

    async def list_tags(self) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM tags ORDER BY name")
        return [dict(r) for r in rows]

    async def get_tag(self, tag_id: int) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM tags WHERE id = $1", tag_id)
        return dict(row) if row else None

    async def create_tag(self, data: Dict[str, Any]) -> Dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO tags (name, color) VALUES ($1,$2) RETURNING *",
                data["name"],
                data.get("color", "#8b5cf6"),
            )
        return dict(row)

    async def update_tag(self, tag_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        fields = {k: v for k, v in data.items() if k in {"name", "color"}}
        if not fields:
            return await self.get_tag(tag_id)
        set_clause = ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(fields.keys()))
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE tags SET {set_clause} WHERE id = $1 RETURNING *",
                tag_id,
                *fields.values(),
            )
        return dict(row) if row else None

    async def delete_tag(self, tag_id: int) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM tags WHERE id = $1", tag_id)
        return result != "DELETE 0"

    async def add_tag_to_transaction(self, transaction_id: int, tag_id: int) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO transaction_tags (transaction_id, tag_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                transaction_id,
                tag_id,
            )

    async def remove_tag_from_transaction(self, transaction_id: int, tag_id: int) -> bool:
        pool = await self._pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM transaction_tags WHERE transaction_id = $1 AND tag_id = $2",
                transaction_id,
                tag_id,
            )
        return result != "DELETE 0"

    async def get_tags_for_transaction(self, transaction_id: int) -> List[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.* FROM tags t
                JOIN transaction_tags tt ON tt.tag_id = t.id
                WHERE tt.transaction_id = $1
                ORDER BY t.name
                """,
                transaction_id,
            )
        return [dict(r) for r in rows]
