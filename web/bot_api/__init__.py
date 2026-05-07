"""
Bot API package — REST endpoints under /api/bot/* that power the frontend
"Bot" section. The Telegram bot itself lives in web/telegram/ and reads/writes
the SAME repositories (single source of truth).
"""
from .routes import router

__all__ = ["router"]
