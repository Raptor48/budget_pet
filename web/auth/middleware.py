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
        
        # Check session
        session_token = request.cookies.get("session_token")
        
        if not session_token or session_token not in active_sessions:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"}
            )
        
        # Continue to protected route
        return await call_next(request)
