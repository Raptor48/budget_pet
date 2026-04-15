"""
Unit tests for AuthRepository (users_repo.py).
These tests run against a real DB when DATABASE_URL is set,
or are skipped otherwise.
"""

import os
import pytest
import pytest_asyncio
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from web.auth.users_repo import AuthRepository


# ---------------------------------------------------------------------------
# Password helpers (no DB needed)
# ---------------------------------------------------------------------------

class TestPasswordHelpers:
    def test_hash_and_verify(self):
        hashed = AuthRepository.hash_password("secret123")
        assert hashed != "secret123"
        assert AuthRepository.verify_password("secret123", hashed)

    def test_wrong_password_rejected(self):
        hashed = AuthRepository.hash_password("correct")
        assert not AuthRepository.verify_password("wrong", hashed)

    def test_hash_is_unique(self):
        h1 = AuthRepository.hash_password("same")
        h2 = AuthRepository.hash_password("same")
        assert h1 != h2  # bcrypt uses random salt

    def test_verify_invalid_hash_returns_false(self):
        assert not AuthRepository.verify_password("pass", "not-a-valid-hash")


# ---------------------------------------------------------------------------
# DB-backed tests — skipped if no real DB is available
# ---------------------------------------------------------------------------

DB_URL = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
skip_no_db = pytest.mark.skipif(
    not DB_URL or "localhost" not in (DB_URL or ""),
    reason="No local test database available",
)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="module")
async def repo():
    if not DB_URL:
        pytest.skip("DATABASE_URL not set")
    r = AuthRepository(DB_URL)
    # Run migrations on test DB
    from web.auth.db_migration import CREATE_USERS_TABLE, CREATE_SESSIONS_TABLE
    from web.auth.db_migration import CREATE_SESSIONS_USER_IDX, CREATE_SESSIONS_EXPIRES_IDX
    pool = await r.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(CREATE_USERS_TABLE)
        await conn.execute(CREATE_SESSIONS_TABLE)
        await conn.execute(CREATE_SESSIONS_USER_IDX)
        await conn.execute(CREATE_SESSIONS_EXPIRES_IDX)
        # Clean up any leftover test data
        await conn.execute("DELETE FROM sessions")
        await conn.execute("DELETE FROM users")
    yield r
    await r.close()


@skip_no_db
class TestUsersCRUD:
    @pytest.mark.asyncio
    async def test_create_and_get_user(self, repo):
        hashed = AuthRepository.hash_password("pass1")
        user = await repo.create_user("alice", hashed, is_owner=True)
        assert user["username"] == "alice"
        assert user["is_owner"] is True
        assert "id" in user

        fetched = await repo.get_user_by_username("alice")
        assert fetched is not None
        assert fetched["username"] == "alice"
        assert fetched["password_hash"] == hashed

    @pytest.mark.asyncio
    async def test_get_nonexistent_user_returns_none(self, repo):
        result = await repo.get_user_by_username("nobody_xyz")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_users(self, repo):
        users = await repo.list_users()
        assert any(u["username"] == "alice" for u in users)
        for u in users:
            assert "password_hash" not in u

    @pytest.mark.asyncio
    async def test_ensure_owner_exists_upsert(self, repo):
        hashed = AuthRepository.hash_password("newpass")
        owner = await repo.ensure_owner_exists("alice", hashed)
        assert owner["is_owner"] is True
        assert owner["username"] == "alice"

    @pytest.mark.asyncio
    async def test_delete_last_owner_raises(self, repo):
        with pytest.raises(ValueError, match="last owner"):
            await repo.delete_user(
                (await repo.get_user_by_username("alice"))["id"]
            )

    @pytest.mark.asyncio
    async def test_delete_non_owner_user(self, repo):
        hashed = AuthRepository.hash_password("pass2")
        bob = await repo.create_user("bob_test", hashed, is_owner=False)
        await repo.delete_user(bob["id"])
        assert await repo.get_user_by_id(bob["id"]) is None


@skip_no_db
class TestSessions:
    @pytest.mark.asyncio
    async def test_create_and_get_session(self, repo):
        alice = await repo.get_user_by_username("alice")
        token = await repo.create_session(alice["id"], expires_days=30)
        assert len(token) > 20

        user = await repo.get_session_user(token)
        assert user is not None
        assert user["username"] == "alice"

    @pytest.mark.asyncio
    async def test_expired_session_returns_none(self, repo):
        alice = await repo.get_user_by_username("alice")
        token = await repo.create_session(alice["id"], expires_days=-1)
        user = await repo.get_session_user(token)
        assert user is None

    @pytest.mark.asyncio
    async def test_delete_session(self, repo):
        alice = await repo.get_user_by_username("alice")
        token = await repo.create_session(alice["id"])
        await repo.delete_session(token)
        assert await repo.get_session_user(token) is None

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self, repo):
        alice = await repo.get_user_by_username("alice")
        # Create an expired session
        expired_token = await repo.create_session(alice["id"], expires_days=-1)
        await repo.cleanup_expired_sessions()
        assert await repo.get_session_user(expired_token) is None
