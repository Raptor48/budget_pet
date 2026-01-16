"""
Authentication middleware for FastAPI.
Protects all API routes except auth endpoints.
"""

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .routes import active_sessions


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware to protect API routes with session authentication."""
    
    async def dispatch(self, request: Request, call_next):
        # Skip auth for non-API routes
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        
        # Skip auth for auth endpoints
        if request.url.path.startswith("/api/auth/"):
            return await call_next(request)
        
        # Skip auth for health check
        if request.url.path == "/api/healthz":
            return await call_next(request)
        
        # Skip auth for CORS preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)
        
        # Check session from cookie OR Authorization header (Safari compatibility)
        session_token = request.cookies.get("session_token")
        
        # Fallback to Authorization header for Safari with cross-site tracking enabled
        if not session_token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                session_token = auth_header.replace("Bearer ", "").strip()
        
        if not session_token:
            return JSONResponse(
                status_code=401,
                content={"detail": "No session token found in cookies or Authorization header"}
            )
        
        if session_token not in active_sessions:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired session token"}
            )
        
        # Continue to protected route
        return await call_next(request)
