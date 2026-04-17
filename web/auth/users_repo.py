"""
Repository for users and sessions — asyncpg (PostgreSQL).
All password hashing uses bcrypt with cost factor 12.
"""

import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
import bcrypt

logger = logging.getLogger(__name__)

_auth_repo: Optional["AuthRepository"] = None


class AuthRepository:
    def __init__(self) -> None:
        pass

    async def get_pool(self) -> asyncpg.Pool:
        from web.db import get_pool as _get_shared_pool
        return await _get_shared_pool()

    async def close(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    async def get_user_by_username(self, username: str) -> Optional[dict]:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, username, password_hash, is_owner, created_at "
                "FROM users WHERE username = $1",
                username,
            )
        return dict(row) if row else None

    async def get_user_by_id(self, user_id: int) -> Optional[dict]:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, username, password_hash, is_owner, created_at "
                "FROM users WHERE id = $1",
                user_id,
            )
        return dict(row) if row else None

    async def create_user(
        self, username: str, password_hash: str, is_owner: bool = False
    ) -> dict:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO users (username, password_hash, is_owner) "
                "VALUES ($1, $2, $3) "
                "RETURNING id, username, is_owner, created_at",
                username,
                password_hash,
                is_owner,
            )
        return dict(row)

    async def list_users(self) -> list[dict]:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, username, is_owner, created_at FROM users ORDER BY id"
            )
        return [dict(r) for r in rows]

    async def delete_user(self, user_id: int) -> None:
        """Delete a user. Raises ValueError if it would remove the last owner."""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            owner_count = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE is_owner = TRUE"
            )
            target = await conn.fetchrow(
                "SELECT is_owner FROM users WHERE id = $1", user_id
            )
            if target is None:
                raise ValueError("User not found")
            if target["is_owner"] and owner_count <= 1:
                raise ValueError("Cannot delete the last owner account")
            await conn.execute("DELETE FROM users WHERE id = $1", user_id)

    async def ensure_owner_exists(self, username: str, password_hash: str) -> dict:
        """
        Upsert: create owner if username doesn't exist; if it does exist,
        update password_hash and ensure is_owner=TRUE.
        Used for emergency env-var bypass.
        """
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO users (username, password_hash, is_owner)
                VALUES ($1, $2, TRUE)
                ON CONFLICT (username) DO UPDATE
                  SET password_hash = EXCLUDED.password_hash,
                      is_owner = TRUE
                RETURNING id, username, is_owner, created_at
                """,
                username,
                password_hash,
            )
        return dict(row)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def create_session(self, user_id: int, expires_days: int = 30) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES ($1, $2, $3)",
                token,
                user_id,
                expires_at,
            )
        return token

    async def get_session_user(self, token: str) -> Optional[dict]:
        """Return the user for a valid, non-expired session token."""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT u.id, u.username, u.is_owner, u.created_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = $1 AND s.expires_at > NOW()
                """,
                token,
            )
        return dict(row) if row else None

    async def delete_session(self, token: str) -> None:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM sessions WHERE token = $1", token)

    async def cleanup_expired_sessions(self) -> None:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM sessions WHERE expires_at < NOW()")

    # ------------------------------------------------------------------
    # Password helpers (static, no DB)
    # ------------------------------------------------------------------

    @staticmethod
    def hash_password(plain: str) -> str:
        return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(plain.encode(), hashed.encode())
        except Exception:
            return False


def get_auth_repo() -> AuthRepository:
    global _auth_repo
    if _auth_repo is None:
        _auth_repo = AuthRepository()
    return _auth_repo
