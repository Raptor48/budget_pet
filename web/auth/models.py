"""
Pydantic models for authentication.
"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Login request model."""
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


class LoginResponse(BaseModel):
    """Login response model."""
    success: bool
    message: str
    user: dict | None = None
    token: str | None = None  # Token for Authorization header (Safari compatibility)


class User(BaseModel):
    """User model."""
    username: str
    logged_in_at: str
