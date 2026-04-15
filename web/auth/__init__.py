"""
Authentication module for budget app.
Session-based authentication backed by PostgreSQL.
"""

from .routes import router as auth_router
from .middleware import AuthMiddleware

__all__ = ["auth_router", "AuthMiddleware"]
