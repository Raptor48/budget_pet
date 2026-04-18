"""Repository for audit_log — asyncpg."""
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_VALID_SOURCES = {"manual", "scheduler", "webhook", "system"}


class AuditRepository:
    async def _pool(self):
        from web.db import get_pool
        return await get_pool()

    async def insert(
        self,
        *,
        event_type: str,
        source: str,
        actor_user_id: Optional[int] = None,
        actor_username: Optional[str] = None,
        target_kind: Optional[str] = None,
        target_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        request_ip: Optional[str] = None,
    ) -> Optional[int]:
        if source not in _VALID_SOURCES:
            raise ValueError(f"Invalid audit source: {source!r}")
        if not event_type:
            raise ValueError("event_type is required")

        payload = json.dumps(metadata or {}, default=str)
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO audit_log
                    (actor_user_id, actor_username, event_type, source,
                     target_kind, target_id, metadata, request_ip)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::inet)
                RETURNING id
                """,
                actor_user_id,
                actor_username,
                event_type,
                source,
                target_kind,
                target_id,
                payload,
                request_ip,
            )
        return int(row["id"]) if row else None

    async def list(
        self,
        *,
        limit: int = 50,
        before_id: Optional[int] = None,
        event_type: Optional[str] = None,
        event_prefix: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return newest-first entries. `event_prefix` lets callers filter by
        a category like 'plaid.' or 'auth.' without needing an exact match.
        """
        limit = max(1, min(500, int(limit)))
        clauses: List[str] = []
        args: List[Any] = []

        if before_id is not None:
            args.append(int(before_id))
            clauses.append(f"id < ${len(args)}")
        if event_type:
            args.append(event_type)
            clauses.append(f"event_type = ${len(args)}")
        if event_prefix:
            args.append(f"{event_prefix}%")
            clauses.append(f"event_type LIKE ${len(args)}")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(limit)
        query = f"""
            SELECT id, created_at, actor_user_id, actor_username, event_type,
                   source, target_kind, target_id, metadata, request_ip::text AS request_ip
            FROM audit_log
            {where}
            ORDER BY id DESC
            LIMIT ${len(args)}
        """

        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)

        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            raw_meta = d.get("metadata")
            if isinstance(raw_meta, str):
                try:
                    d["metadata"] = json.loads(raw_meta)
                except Exception:
                    d["metadata"] = {}
            elif raw_meta is None:
                d["metadata"] = {}
            out.append(d)
        return out

    async def event_types(self) -> List[str]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT event_type FROM audit_log ORDER BY event_type"
            )
        return [r["event_type"] for r in rows]


_repo: Optional[AuditRepository] = None


def get_audit_repo() -> AuditRepository:
    global _repo
    if _repo is None:
        _repo = AuditRepository()
    return _repo
