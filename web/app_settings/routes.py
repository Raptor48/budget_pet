"""FastAPI routes for application-wide settings."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from web.audit import record as audit_record

from .models import AutosyncConfigOut, AutosyncConfigUpdate
from .repo import get_app_settings_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _row_to_out(row: dict, next_run_at=None) -> AutosyncConfigOut:
    return AutosyncConfigOut(
        enabled=bool(row["autosync_enabled"]),
        hour_utc=int(row["autosync_hour_utc"]),
        minute_utc=int(row["autosync_minute_utc"]),
        updated_at=row.get("updated_at"),
        updated_by_username=row.get("updated_by_username"),
        next_run_at=next_run_at,
    )


def _next_run_at() -> Optional[object]:
    try:
        from web.plaid.scheduler import get_scheduler_status
        status = get_scheduler_status()
        return status.get("next_run_at")
    except Exception:
        return None


@router.get("/app", response_model=AutosyncConfigOut)
async def get_app_settings():
    repo = get_app_settings_repo()
    row = await repo.get()
    return _row_to_out(row, next_run_at=_next_run_at())


@router.patch("/app", response_model=AutosyncConfigOut)
async def update_app_settings(body: AutosyncConfigUpdate, request: Request):
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    try:
        uid_int = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        uid_int = None

    repo = get_app_settings_repo()
    try:
        row = await repo.update(
            enabled=body.enabled,
            hour_utc=body.hour_utc,
            minute_utc=body.minute_utc,
            updated_by=uid_int,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Reschedule the cron job live so the change takes effect without a redeploy.
    try:
        from web.plaid.scheduler import apply_autosync_config
        apply_autosync_config(
            enabled=bool(row["autosync_enabled"]),
            hour_utc=int(row["autosync_hour_utc"]),
            minute_utc=int(row["autosync_minute_utc"]),
        )
    except Exception as exc:
        logger.warning("apply_autosync_config failed: %s", exc)

    await audit_record(
        "settings.autosync_updated",
        source="manual",
        request=request,
        metadata={
            "enabled": bool(row["autosync_enabled"]),
            "hour_utc": int(row["autosync_hour_utc"]),
            "minute_utc": int(row["autosync_minute_utc"]),
        },
    )

    return _row_to_out(row, next_run_at=_next_run_at())
