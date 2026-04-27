"""
Telegram bot package — webhook mode, runs in-process with FastAPI.

Public surface:

* ``router``  — FastAPI router with the webhook endpoint
* ``runtime`` — bootstrap / shutdown helpers
* ``handlers`` — command + callback handlers
"""
from .router import router

__all__ = ["router"]
