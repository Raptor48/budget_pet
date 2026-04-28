"""FastAPI routes for application-wide settings."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from web.audit import record as audit_record

from .models import AutosyncConfigOut, AutosyncConfigUpdate, WebhookReconcileResult
from .repo import get_app_settings_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _row_to_out(
    row: dict,
    *,
    next_run_at=None,
    webhook_reconcile: Optional[dict] = None,
) -> AutosyncConfigOut:
    from web.plaid.webhook_config import configured_webhook_url

    return AutosyncConfigOut(
        frequency=str(row["autosync_frequency"]),  # type: ignore[arg-type]
        hour_utc=int(row["autosync_hour_utc"]),
        minute_utc=int(row["autosync_minute_utc"]),
        webhooks_enabled=bool(row.get("webhooks_enabled", True)),
        bot_activity_auto_prune_enabled=bool(
            row.get("bot_activity_auto_prune_enabled", True)
        ),
        audit_log_auto_prune_enabled=bool(
            row.get("audit_log_auto_prune_enabled", False)
        ),
        updated_at=row.get("updated_at"),
        updated_by_username=row.get("updated_by_username"),
        next_run_at=next_run_at,
        webhook_url_configured=bool(configured_webhook_url()),
        webhook_reconcile=(
            WebhookReconcileResult(**webhook_reconcile)
            if webhook_reconcile is not None
            else None
        ),
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
    # Capture the previous webhooks flag so we only push to Plaid when it changes.
    previous = await repo.get()
    prev_webhooks_enabled = bool(previous.get("webhooks_enabled", True))

    try:
        row = await repo.update(
            frequency=body.frequency,
            hour_utc=body.hour_utc,
            minute_utc=body.minute_utc,
            webhooks_enabled=body.webhooks_enabled,
            bot_activity_auto_prune_enabled=body.bot_activity_auto_prune_enabled,
            audit_log_auto_prune_enabled=body.audit_log_auto_prune_enabled,
            updated_by=uid_int,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Reschedule the cron job live so the autosync change takes effect without a redeploy.
    try:
        from web.plaid.scheduler import apply_autosync_config
        apply_autosync_config(
            frequency=str(row["autosync_frequency"]),
            hour_utc=int(row["autosync_hour_utc"]),
            minute_utc=int(row["autosync_minute_utc"]),
        )
    except Exception as exc:
        logger.warning("apply_autosync_config failed: %s", exc)

    # Push the webhook change to Plaid if (and only if) the flag just flipped.
    # Clearing webhooks at Plaid is what actually stops the $0.10 Balance calls —
    # ignoring them locally wouldn't change our bill.
    webhook_reconcile: Optional[dict] = None
    new_webhooks_enabled = bool(row.get("webhooks_enabled", True))
    if new_webhooks_enabled != prev_webhooks_enabled:
        try:
            from web.plaid.webhook_config import reconcile_item_webhooks
            webhook_reconcile = await reconcile_item_webhooks(new_webhooks_enabled)
        except Exception as exc:
            logger.error("reconcile_item_webhooks raised: %s", exc)
            webhook_reconcile = {
                "updated": 0,
                "failed": 0,
                "total": 0,
                "errors": [f"reconcile failed: {exc}"],
            }

    await audit_record(
        "settings.autosync_updated",
        source="manual",
        request=request,
        metadata={
            "frequency": str(row["autosync_frequency"]),
            "hour_utc": int(row["autosync_hour_utc"]),
            "minute_utc": int(row["autosync_minute_utc"]),
            "webhooks_enabled": new_webhooks_enabled,
            **(
                {"webhook_reconcile": webhook_reconcile}
                if webhook_reconcile is not None
                else {}
            ),
        },
    )

    return _row_to_out(
        row,
        next_run_at=_next_run_at(),
        webhook_reconcile=webhook_reconcile,
    )
