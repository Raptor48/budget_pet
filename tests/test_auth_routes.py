"""
Integration tests for auth routes.
Uses mocked AuthRepository so no real DB is needed.
"""

import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

# Ensure env vars are set before importing app
os.environ.setdefault("ADMIN_LOGIN", "testadmin")
os.environ.setdefault("ADMIN_PASSWORD", "testpassword123")
os.environ.setdefault("DATABASE_URL", "postgresql://fake/fake")

from web.auth.users_repo import AuthRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_repo():
    """Return a mock AuthRepository with sensible defaults."""
    repo = MagicMock(spec=AuthRepository)
    repo.get_user_by_username = AsyncMock(return_value=None)
    repo.get_user_by_id = AsyncMock(return_value=None)
    repo.create_user = AsyncMock()
    repo.list_users = AsyncMock(return_value=[])
    repo.delete_user = AsyncMock()
    repo.ensure_owner_exists = AsyncMock(return_value={
        "id": 1, "username": "testadmin", "is_owner": True,
    })
    repo.create_session = AsyncMock(return_value="mock-token-abc")
    repo.get_session_user = AsyncMock(return_value=None)
    repo.delete_session = AsyncMock()
    repo.cleanup_expired_sessions = AsyncMock()
    repo.hash_password = AuthRepository.hash_password
    repo.verify_password = AuthRepository.verify_password
    return repo


@pytest.fixture
def client(mock_repo):
    with patch("web.auth.routes.get_auth_repo", return_value=mock_repo), \
         patch("web.auth.middleware.get_auth_repo", return_value=mock_repo):
        from web.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c, mock_repo


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_env_bypass_success(self, client):
        c, repo = client
        response = c.post("/api/auth/login", json={
            "username": "testadmin",
            "password": "testpassword123",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "token" in data  # token included as Bearer fallback for cross-origin
        assert "session_token" in response.cookies
        repo.ensure_owner_exists.assert_called_once()
        repo.create_session.assert_called_once()

    def test_invalid_credentials(self, client):
        c, repo = client
        repo.get_user_by_username = AsyncMock(return_value=None)
        response = c.post("/api/auth/login", json={
            "username": "nobody",
            "password": "wrong",
        })
        assert response.status_code == 401
        assert "token" not in response.json()

    def test_db_user_login(self, client):
        c, repo = client
        hashed = AuthRepository.hash_password("mypassword")
        repo.get_user_by_username = AsyncMock(return_value={
            "id": 2, "username": "anna", "password_hash": hashed, "is_owner": False,
        })
        response = c.post("/api/auth/login", json={
            "username": "anna",
            "password": "mypassword",
        })
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "session_token" in response.cookies

    def test_rate_limiting(self, client):
        c, repo = client
        repo.get_user_by_username = AsyncMock(return_value=None)
        # 5 failed attempts
        for _ in range(5):
            c.post("/api/auth/login", json={"username": "x", "password": "wrong"})
        # 6th should be rate-limited
        response = c.post("/api/auth/login", json={"username": "x", "password": "wrong"})
        assert response.status_code == 429
        assert "Retry-After" in response.headers


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_logout_clears_session(self, client):
        c, repo = client
        response = c.post(
            "/api/auth/logout",
            cookies={"session_token": "some-token"},
        )
        assert response.status_code == 200
        repo.delete_session.assert_called_with("some-token")

    def test_logout_without_cookie(self, client):
        c, _ = client
        response = c.post("/api/auth/logout")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# /me endpoint
# ---------------------------------------------------------------------------

class TestMe:
    def test_me_authenticated(self, client):
        c, repo = client
        repo.get_session_user = AsyncMock(return_value={
            "id": 1, "username": "testadmin", "is_owner": True,
        })
        response = c.get("/api/auth/me", cookies={"session_token": "valid"})
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["username"] == "testadmin"
        assert data["user"]["is_owner"] is True

    def test_me_no_cookie(self, client):
        c, _ = client
        response = c.get("/api/auth/me")
        assert response.status_code == 401

    def test_me_expired_session(self, client):
        c, repo = client
        repo.get_session_user = AsyncMock(return_value=None)
        response = c.get("/api/auth/me", cookies={"session_token": "expired"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

class TestUserManagement:
    def _owner_client(self, client):
        c, repo = client
        repo.get_session_user = AsyncMock(return_value={
            "id": 1, "username": "testadmin", "is_owner": True,
        })
        return c, repo

    def _member_client(self, client):
        c, repo = client
        repo.get_session_user = AsyncMock(return_value={
            "id": 2, "username": "anna", "is_owner": False,
        })
        return c, repo

    def test_list_users_owner(self, client):
        c, repo = self._owner_client(client)
        repo.list_users = AsyncMock(return_value=[
            {"id": 1, "username": "testadmin", "is_owner": True, "created_at": "2026-01-01T00:00:00+00:00"},
        ])
        response = c.get("/api/auth/users", cookies={"session_token": "tok"})
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_list_users_non_owner_forbidden(self, client):
        c, repo = self._member_client(client)
        response = c.get("/api/auth/users", cookies={"session_token": "tok"})
        assert response.status_code == 403

    def test_create_user_owner(self, client):
        c, repo = self._owner_client(client)
        repo.get_user_by_username = AsyncMock(return_value=None)
        repo.create_user = AsyncMock(return_value={
            "id": 3, "username": "newuser", "is_owner": False,
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        response = c.post(
            "/api/auth/users",
            json={"username": "newuser", "password": "password123"},
            cookies={"session_token": "tok"},
        )
        assert response.status_code == 201
        assert response.json()["username"] == "newuser"

    def test_create_user_duplicate_rejected(self, client):
        c, repo = self._owner_client(client)
        repo.get_user_by_username = AsyncMock(return_value={"id": 5, "username": "existing"})
        response = c.post(
            "/api/auth/users",
            json={"username": "existing", "password": "password123"},
            cookies={"session_token": "tok"},
        )
        assert response.status_code == 409

    def test_delete_user_owner(self, client):
        c, repo = self._owner_client(client)
        response = c.delete("/api/auth/users/2", cookies={"session_token": "tok"})
        assert response.status_code == 204

    def test_delete_self_forbidden(self, client):
        c, repo = self._owner_client(client)
        response = c.delete("/api/auth/users/1", cookies={"session_token": "tok"})
        assert response.status_code == 400

    def test_protected_route_requires_session(self, client):
        c, repo = client
        repo.get_session_user = AsyncMock(return_value=None)
        response = c.get("/api/auth/users", cookies={"session_token": "bad"})
        assert response.status_code == 401
