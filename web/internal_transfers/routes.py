"""FastAPI routes for internal-transfer settings and manual re-scan.

Endpoints:
  * ``GET  /api/settings/internal-transfers`` — current names list.
  * ``PUT  /api/settings/internal-transfers`` — replace names list.
    Automatically re-scans the last 90 days so new names apply
    retroactively without the user clicking a second button.
  * ``POST /api/settings/internal-transfers/rescan`` — re-run the
    classifier. ``horizon=all_time`` covers full history; default is
    ``last_90_days`` for safety.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from web.audit import record as audit_record
from web.db import get_pool
from web.plaid.internal_transfer import normalize_names, rescan_internal_transfers

from .models import (
    InternalTransferRescanRequest,
    InternalTransferRescanResult,
    InternalTransferSettingsOut,
    InternalTransferSettingsUpdate,
)
from .repo import get_internal_transfer_settings_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings/internal-transfers", tags=["settings"])


def _actor_uid(request: Request) -> Optional[int]:
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    try:
        return int(uid) if uid is not None else None
    except (TypeError, ValueError):
        return None


async def _rescan(horizon_days: Optional[int]) -> int:
    """Acquire a connection and invoke the classifier's rescan routine."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await rescan_internal_transfers(conn, horizon_days=horizon_days)


@router.get("", response_model=InternalTransferSettingsOut)
async def get_internal_transfer_settings():
    repo = get_internal_transfer_settings_repo()
    names = await repo.get_names()
    return InternalTransferSettingsOut(
        names=names,
        normalized_names=normalize_names(names),
    )


@router.put("", response_model=InternalTransferSettingsOut)
async def update_internal_transfer_settings(
    body: InternalTransferSettingsUpdate, request: Request
):
    repo = get_internal_transfer_settings_repo()
    stored = await repo.set_names(body.names)

    # After editing the list, auto-reclassify the last 90 days so the change
    # shows up in the UI immediately. Full-history cleanups remain a
    # separate explicit action because they can touch many rows.
    try:
        updated = await _rescan(horizon_days=90)
    except Exception as exc:
        logger.warning("Auto-rescan after names update failed: %s", exc)
        updated = 0

    await audit_record(
        "settings.internal_transfer_names_updated",
        source="manual",
        request=request,
        metadata={
            "count": len(stored),
            "rescan_rows_updated": updated,
        },
    )

    return InternalTransferSettingsOut(
        names=stored,
        normalized_names=normalize_names(stored),
    )


@router.post("/rescan", response_model=InternalTransferRescanResult)
async def rescan_internal_transfer_matches(
    body: InternalTransferRescanRequest,
    request: Request,
):
    horizon_days: Optional[int] = 90 if body.horizon == "last_90_days" else None
    try:
        updated = await _rescan(horizon_days=horizon_days)
    except Exception as exc:
        logger.error("Internal-transfer rescan failed: %s", exc)
        raise HTTPException(status_code=500, detail="Rescan failed") from exc

    repo = get_internal_transfer_settings_repo()
    names = await repo.get_names()

    await audit_record(
        "settings.internal_transfer_rescan",
        source="manual",
        request=request,
        metadata={
            "horizon": body.horizon,
            "rows_updated": updated,
            "configured_names_count": len(names),
        },
    )

    return InternalTransferRescanResult(
        rows_updated=updated,
        horizon=body.horizon,
        configured_names_count=len(names),
    )
