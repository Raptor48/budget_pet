"""
Database migration for auth tables.
Called at application startup — safe to run repeatedly (IF NOT EXISTS).
"""

import logging

logger = logging.getLogger(__name__)

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id           SERIAL PRIMARY KEY,
    username     TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_owner     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    token        TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at   TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

CREATE_SESSIONS_USER_IDX = """
CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id)
"""

CREATE_SESSIONS_EXPIRES_IDX = """
CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions(expires_at)
"""


async def run_migrations() -> None:
    """Create auth tables if they do not exist."""
    from .users_repo import get_auth_repo
    repo = get_auth_repo()
    pool = await repo.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(CREATE_USERS_TABLE)
        await conn.execute(CREATE_SESSIONS_TABLE)
        await conn.execute(CREATE_SESSIONS_USER_IDX)
        await conn.execute(CREATE_SESSIONS_EXPIRES_IDX)
    logger.info("Auth migrations applied")
