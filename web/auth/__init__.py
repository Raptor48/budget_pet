"""
Authentication module for budget app.
Simple session-based authentication with admin credentials.
"""

from .routes import router as auth_router
from .middleware import AuthMiddleware

__all__ = ["auth_router", "AuthMiddleware"]
