"""
Authentication middleware for FastAPI.
Protects all /api/* routes except auth and health endpoints.
Session lookup is backed by PostgreSQL via AuthRepository.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .users_repo import get_auth_repo

_SKIP_PREFIXES = ("/api/auth/",)
_SKIP_EXACT = {"/api/healthz"}
# Plaid verifies webhooks with JWT (see docs/plaid.md); no session cookie on this path.
# Telegram verifies the secret-token header (see web/telegram/router.py); no session either.
_SKIP_WEBHOOK_PATHS = {
    "/api/plaid/webhook",
    "/api/telegram/webhook",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only protect /api/* routes
        if not path.startswith("/api/"):
            return await call_next(request)

        # Skip auth endpoints and health check
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)
        if path in _SKIP_EXACT or path in _SKIP_WEBHOOK_PATHS:
            return await call_next(request)

        # CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)

        token = request.cookies.get("session_token")
        # Fallback: Authorization: Bearer header for cross-origin cookie restrictions
        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()

        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )

        repo = get_auth_repo()
        user = await repo.get_session_user(token)
        if not user:
            return JSONResponse(
                status_code=401,
                content={"detail": "Session expired or invalid"},
            )

        # Attach user to request state for downstream handlers
        request.state.user = user
        return await call_next(request)
