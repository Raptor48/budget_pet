"""Pydantic models for the app-settings module."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AutosyncConfig(BaseModel):
    """Schedule for the daily Plaid auto-sync.

    Time is stored and transmitted in UTC to keep server and DB aligned;
    the frontend converts to/from the browser's local time zone for display.
    """

    enabled: bool = True
    hour_utc: int = Field(3, ge=0, le=23)
    minute_utc: int = Field(0, ge=0, le=59)


class AutosyncConfigOut(AutosyncConfig):
    updated_at: Optional[datetime] = None
    updated_by_username: Optional[str] = None
    next_run_at: Optional[datetime] = None


class AutosyncConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    hour_utc: Optional[int] = Field(None, ge=0, le=23)
    minute_utc: Optional[int] = Field(None, ge=0, le=59)
