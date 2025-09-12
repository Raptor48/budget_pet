"""
Authentication routes for FastAPI.
Session-based authentication with secure cookies.
"""

import os
import secrets
from datetime import datetime, timedelta
from typing import Dict
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .models import LoginRequest, LoginResponse, User

router = APIRouter(prefix="/api/auth", tags=["auth"])

# In-memory session storage (for simplicity)
# In production, use Redis or database
active_sessions: Dict[str, User] = {}

# Admin credentials from environment
ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "XmMYS7r4TeYcNEp")


@router.post("/login", response_model=LoginResponse)
async def login(login_data: LoginRequest, response: Response):
    """Login endpoint - creates session cookie."""
    
    # Check credentials
    if login_data.username != ADMIN_LOGIN or login_data.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Generate session token
    session_token = secrets.token_urlsafe(32)
    
    # Create user session
    user = User(
        username=login_data.username,
        logged_in_at=datetime.now().isoformat()
    )
    active_sessions[session_token] = user
    
    # Set secure cookie (30 days)
    response.set_cookie(
        key="session_token",
        value=session_token,
        max_age=30 * 24 * 60 * 60,  # 30 days in seconds
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax"
    )
    
    return LoginResponse(
        success=True,
        message="Login successful",
        user=user.dict()
    )


@router.post("/logout")
async def logout(request: Request, response: Response):
    """Logout endpoint - removes session."""
    
    session_token = request.cookies.get("session_token")
    
    if session_token and session_token in active_sessions:
        del active_sessions[session_token]
    
    # Clear cookie
    response.delete_cookie("session_token")
    
    return {"success": True, "message": "Logged out successfully"}


@router.get("/me")
async def get_current_user(request: Request):
    """Get current user info."""
    
    session_token = request.cookies.get("session_token")
    
    if not session_token or session_token not in active_sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user = active_sessions[session_token]
    return {"user": user.dict(), "authenticated": True}


@router.get("/status")
async def auth_status(request: Request):
    """Check authentication status."""
    
    session_token = request.cookies.get("session_token")
    authenticated = session_token is not None and session_token in active_sessions
    
    return {"authenticated": authenticated}
