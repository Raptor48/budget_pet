"""
Pydantic models for authentication.
"""

from datetime import datetime
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


class LoginResponse(BaseModel):
    success: bool
    message: str
    user: dict | None = None


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(..., min_length=6, max_length=100)


class UserPublic(BaseModel):
    id: int
    username: str
    is_owner: bool
    created_at: datetime


class User(BaseModel):
    """Legacy compat — used by middleware request.state.user."""
    id: int
    username: str
    is_owner: bool
