"""Pydantic models for the app-settings module."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# Keep this tuple as the single source of truth for the supported values;
# the DB CHECK constraint and scheduler cron-builder mirror it.
AUTOSYNC_FREQUENCIES = ("off", "daily", "weekly", "semimonthly", "monthly")
AutosyncFrequency = Literal["off", "daily", "weekly", "semimonthly", "monthly"]


class AutosyncConfig(BaseModel):
    """Schedule for the Plaid auto-sync and the webhook toggle.

    ``frequency`` picks one of five cadences; ``hour_utc`` / ``minute_utc``
    set the time-of-day for every cadence. Anchor days are fixed to keep the
    UI simple:

    * ``daily``        — runs every day at ``HH:MM`` UTC.
    * ``weekly``       — runs every Sunday at ``HH:MM`` UTC.
    * ``semimonthly``  — runs on the 1st and 15th of each month at ``HH:MM`` UTC.
    * ``monthly``      — runs on the 1st of each month at ``HH:MM`` UTC.
    * ``off``          — no scheduled runs; manual sync still works.

    Time is stored and transmitted in UTC to keep server and DB aligned;
    the frontend converts to/from the browser's local time zone for display.

    ``webhooks_enabled`` controls whether Plaid pushes real-time updates
    (``SYNC_UPDATES_AVAILABLE`` / ``ITEM_LOGIN_REQUIRED`` / ...) to our
    ``/api/plaid/webhook`` endpoint. Turning it off silences every
    webhook-triggered Balance call ($0.10 each) — the scheduled autosync
    still runs at the chosen cadence.
    """

    frequency: AutosyncFrequency = "daily"
    hour_utc: int = Field(3, ge=0, le=23)
    minute_utc: int = Field(0, ge=0, le=59)
    webhooks_enabled: bool = True
    # Auto-prune toggles for the two log surfaces. Window is fixed at 7
    # days when the toggle is on; off means the daily prune skips the
    # table (manual clear from the UI still works). Defaults match the
    # DB: bot activity rolls fast, audit log is kept by default.
    bot_activity_auto_prune_enabled: bool = True
    audit_log_auto_prune_enabled: bool = False


class WebhookReconcileResult(BaseModel):
    """Outcome of calling Plaid ``/item/webhook/update`` on every linked item."""

    updated: int = 0
    failed: int = 0
    total: int = 0
    errors: list[str] = []


class AutosyncConfigOut(AutosyncConfig):
    updated_at: Optional[datetime] = None
    updated_by_username: Optional[str] = None
    next_run_at: Optional[datetime] = None
    webhook_url_configured: bool = True
    webhook_reconcile: Optional[WebhookReconcileResult] = None


class AutosyncConfigUpdate(BaseModel):
    frequency: Optional[AutosyncFrequency] = None
    hour_utc: Optional[int] = Field(None, ge=0, le=23)
    minute_utc: Optional[int] = Field(None, ge=0, le=59)
    webhooks_enabled: Optional[bool] = None
    bot_activity_auto_prune_enabled: Optional[bool] = None
    audit_log_auto_prune_enabled: Optional[bool] = None
