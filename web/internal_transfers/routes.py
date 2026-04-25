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
from web.plaid.internal_transfer import (
    normalize_names,
)

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


async def _rescan(horizon_days: Optional[int]) -> tuple[int, int]:
    """Re-run the full four-class classifier over the requested horizon.

    The endpoint still returns two counters (``name_updated``,
    ``pair_updated``) for backwards compatibility with the UI's
    "N rows matched by name / by pair" messaging, but under the hood we
    now call the unified :func:`web.classification.classifier.rescan_all`
    which handles name match + both pair-matcher rules (cash ↔ debt and
    depository ↔ depository) in one pass.

    ``pair_updated`` is reported as the number of pairs found (rows
    divided by two), and ``name_updated`` is ``total_changed − 2 *
    pairs`` so the UI message remains meaningful even though both rules
    live in the same function now.
    """
    from web.classification.classifier import rescan_all

    pool = await get_pool()
    async with pool.acquire() as conn:
        stats = await rescan_all(conn, horizon_days=horizon_days)
    pair_rows = 2 * stats.paired
    name_updated = max(0, stats.changed - pair_rows)
    return name_updated, pair_rows


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
    # separate explicit action because they can touch many rows. The
    # pair-matcher also runs here so the user gets the same "apply to
    # recent history" behavior for the newly-added names and any
    # same-amount transfer pairs that were waiting for the other side to
    # sync.
    name_updated = 0
    pair_updated = 0
    try:
        name_updated, pair_updated = await _rescan(horizon_days=90)
    except Exception as exc:
        logger.warning("Auto-rescan after names update failed: %s", exc)

    await audit_record(
        "settings.internal_transfer_names_updated",
        source="manual",
        request=request,
        metadata={
            "count": len(stored),
            "rescan_rows_updated": name_updated + pair_updated,
            "name_rows_updated": name_updated,
            "pair_rows_updated": pair_updated,
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
        name_updated, pair_updated = await _rescan(horizon_days=horizon_days)
    except Exception as exc:
        logger.error("Internal-transfer rescan failed: %s", exc)
        raise HTTPException(status_code=500, detail="Rescan failed") from exc

    repo = get_internal_transfer_settings_repo()
    names = await repo.get_names()

    total_updated = name_updated + pair_updated
    await audit_record(
        "settings.internal_transfer_rescan",
        source="manual",
        request=request,
        metadata={
            "horizon": body.horizon,
            "rows_updated": total_updated,
            "name_rows_updated": name_updated,
            "pair_rows_updated": pair_updated,
            "configured_names_count": len(names),
        },
    )

    return InternalTransferRescanResult(
        rows_updated=total_updated,
        name_rows_updated=name_updated,
        pair_rows_updated=pair_updated,
        horizon=body.horizon,
        configured_names_count=len(names),
    )
