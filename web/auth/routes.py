"""
Authentication routes for FastAPI.
Session-based authentication backed by PostgreSQL.

Emergency bypass: ADMIN_LOGIN + ADMIN_PASSWORD env vars always grant access,
even if the users table is empty or corrupted. This is the permanent admin fallback.
"""

import os
import logging
import time
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, status

from .models import LoginRequest, LoginResponse, UserCreate, UserPublic
from .users_repo import get_auth_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

def validate_admin_credentials() -> None:
    """Raise RuntimeError if admin env vars are not set. Called at startup."""
    if not os.getenv("ADMIN_LOGIN") or not os.getenv("ADMIN_PASSWORD"):
        raise RuntimeError(
            "ADMIN_LOGIN and ADMIN_PASSWORD environment variables must be set. "
            "These are required for emergency admin access."
        )

# -- Rate limiting (in-memory, per IP) --
# Tracks timestamps of failed login attempts: {ip: [timestamp, ...]}
_failed_attempts: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = 60  # seconds


def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    attempts = _failed_attempts[ip]
    # Keep only attempts within the window
    _failed_attempts[ip] = [t for t in attempts if now - t < RATE_LIMIT_WINDOW]
    if len(_failed_attempts[ip]) >= RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again in 60 seconds.",
            headers={"Retry-After": "60"},
        )


def _record_failed_attempt(ip: str) -> None:
    _failed_attempts[ip].append(time.monotonic())


def _clear_failed_attempts(ip: str) -> None:
    _failed_attempts.pop(ip, None)


def _extract_bearer(request: Request) -> Optional[str]:
    """Extract Bearer token from Authorization header (cross-origin fallback)."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    return None


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_production(request: Request) -> bool:
    return (
        os.getenv("RAILWAY_ENVIRONMENT") == "production"
        or os.getenv("RAILWAY") == "true"
        or request.url.scheme == "https"
    )


def _set_session_cookie(response: Response, token: str, is_prod: bool) -> None:
    response.set_cookie(
        key="session_token",
        value=token,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=is_prod,
        samesite="none" if is_prod else "lax",
        domain=None,
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
async def login(login_data: LoginRequest, request: Request, response: Response):
    ip = _get_client_ip(request)
    _check_rate_limit(ip)

    repo = get_auth_repo()
    is_prod = _is_production(request)

    admin_login = os.getenv("ADMIN_LOGIN")
    admin_password = os.getenv("ADMIN_PASSWORD")

    # 1. Emergency env-var bypass — always works
    if login_data.username == admin_login and login_data.password == admin_password:
        _clear_failed_attempts(ip)
        # Hash the plain env password for storage (idempotent upsert)
        password_hash = repo.hash_password(admin_password)
        user = await repo.ensure_owner_exists(admin_login, password_hash)
        await repo.cleanup_expired_sessions()
        token = await repo.create_session(user["id"])
        _set_session_cookie(response, token, is_prod)
        return LoginResponse(
            success=True,
            message="Login successful",
            user={"username": user["username"], "is_owner": user["is_owner"]},
            token=token,
        )

    # 2. Regular DB auth
    user = await repo.get_user_by_username(login_data.username)
    if not user or not repo.verify_password(login_data.password, user["password_hash"]):
        _record_failed_attempt(ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _clear_failed_attempts(ip)
    await repo.cleanup_expired_sessions()
    token = await repo.create_session(user["id"])
    _set_session_cookie(response, token, is_prod)
    return LoginResponse(
        success=True,
        message="Login successful",
        user={"username": user["username"], "is_owner": user["is_owner"]},
        token=token,
    )


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token") or _extract_bearer(request)
    if token:
        repo = get_auth_repo()
        await repo.delete_session(token)
    response.delete_cookie("session_token", path="/")
    return {"success": True, "message": "Logged out successfully"}


@router.get("/me")
async def get_current_user(request: Request):
    token = request.cookies.get("session_token") or _extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    repo = get_auth_repo()
    user = await repo.get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return {
        "user": {"username": user["username"], "is_owner": user["is_owner"]},
        "authenticated": True,
    }


@router.get("/status")
async def auth_status(request: Request):
    token = request.cookies.get("session_token") or _extract_bearer(request)
    if not token:
        return {"authenticated": False}
    repo = get_auth_repo()
    user = await repo.get_session_user(token)
    return {"authenticated": user is not None}


# ------------------------------------------------------------------
# User management (owner only)
# ------------------------------------------------------------------

async def _require_owner(request: Request) -> dict:
    """Return current user if they are an owner, else raise 403."""
    token = request.cookies.get("session_token") or _extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    repo = get_auth_repo()
    user = await repo.get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    if not user["is_owner"]:
        raise HTTPException(status_code=403, detail="Owner access required")
    return user


@router.get("/users", response_model=list[UserPublic])
async def list_users(request: Request):
    await _require_owner(request)
    repo = get_auth_repo()
    users = await repo.list_users()
    return [UserPublic(**u) for u in users]


@router.post("/users", response_model=UserPublic, status_code=201)
async def create_user(user_data: UserCreate, request: Request):
    await _require_owner(request)
    repo = get_auth_repo()
    existing = await repo.get_user_by_username(user_data.username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")
    password_hash = repo.hash_password(user_data.password)
    user = await repo.create_user(user_data.username, password_hash, is_owner=False)
    return UserPublic(**user)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int, request: Request):
    current = await _require_owner(request)
    if current["id"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    repo = get_auth_repo()
    try:
        await repo.delete_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
