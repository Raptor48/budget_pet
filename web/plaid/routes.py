"""
FastAPI routes for Plaid integration — V2.
"""
import json
import logging
from typing import List

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

import os

from web.audit import record as audit_record

from .client import (
    create_link_token,
    exchange_public_token,
    get_institution_metadata,
    get_item_institution_id,
    update_item_webhook,
)
from .models import ExchangeTokenRequest, LinkTokenBody, LinkTokenResponse, PlaidItem, PlaidSyncLogEntry, SyncResult
from .repo import get_plaid_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plaid", tags=["plaid"])


async def _webhooks_enabled() -> bool:
    """Read the in-app webhook toggle. Defaults to True when unavailable.

    Keep this resilient — we never want a DB hiccup during settings read to
    change webhook behaviour in a surprising way. Fail-open matches how the
    app behaved before the toggle existed.
    """
    try:
        from web.app_settings.repo import get_app_settings_repo
        row = await get_app_settings_repo().get()
        return bool(row.get("webhooks_enabled", True))
    except Exception as exc:
        logger.warning("Could not read webhooks_enabled flag, assuming True: %s", exc)
        return True


@router.post("/link-token", response_model=LinkTokenResponse)
async def get_link_token(request: Request, body: LinkTokenBody = Body(default_factory=LinkTokenBody)):
    """Create a Plaid Link token (new connection or update mode when ``item_id`` is sent)."""
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    access_token = None
    if body.item_id:
        repo = get_plaid_repo()
        row = await repo.get_item(body.item_id)
        if not row or row.get("user_id") != int(uid):
            raise HTTPException(status_code=404, detail="Plaid item not found")
        access_token = row.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Item has no access token")
    try:
        # Honour the in-app webhook toggle: when disabled, create the Link
        # token without a webhook URL so Plaid doesn't attach one to the new
        # or updated Item. ``""`` means "no webhook" to our client wrapper.
        override = None if await _webhooks_enabled() else ""
        result = create_link_token(
            user_id=str(uid),
            access_token=access_token,
            webhook_url_override=override,
        )
        return LinkTokenResponse(**result)
    except Exception as exc:
        logger.error("Failed to create link token: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to create link token: {exc}")


@router.post("/exchange-token", response_model=PlaidItem)
async def exchange_token(body: ExchangeTokenRequest, request: Request):
    """Exchange Plaid public_token for permanent access_token and save the connection."""
    try:
        tokens = exchange_public_token(body.public_token)
        access_token = tokens["access_token"]
        item_id = tokens["item_id"]

        # Associate this Plaid item with the currently authenticated user
        current_user = getattr(request.state, "user", None)
        user_id: int | None = current_user["id"] if current_user else None

        # Fetch institution branding (logo + brand color) — fails gracefully
        institution_logo: str | None = None
        institution_color: str | None = None
        institution_id = get_item_institution_id(access_token)
        if institution_id:
            meta = get_institution_metadata(institution_id)
            institution_logo = meta.get("logo")
            institution_color = meta.get("color")

        repo = get_plaid_repo()
        item = await repo.save_item(
            item_id=item_id,
            access_token=access_token,
            institution_name=body.institution_name,
            institution_logo=institution_logo,
            institution_color=institution_color,
            user_id=user_id,
        )

        # Register webhook URL for this item so it receives push notifications.
        # Required for both new connections and re-connections (update mode),
        # but only when the in-app webhook toggle is on. When the toggle is
        # off we intentionally leave the Item without a webhook URL so Plaid
        # never pushes SYNC_UPDATES_AVAILABLE (and never bills the paired
        # Balance call).
        if await _webhooks_enabled():
            webhook_url = (os.getenv("PLAID_WEBHOOK_URL") or "").strip() or None
            if webhook_url:
                update_item_webhook(access_token, webhook_url)

        await audit_record(
            "plaid.item_connect",
            source="manual",
            request=request,
            target_kind="plaid_item",
            target_id=item_id,
            metadata={
                "institution_name": body.institution_name,
                "institution_id": institution_id,
            },
        )

        return PlaidItem(**item)
    except Exception as exc:
        logger.error("Failed to exchange token: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to exchange token: {exc}")


@router.get("/items", response_model=List[PlaidItem])
async def list_items(request: Request):
    """List connected bank items for the current user (owners see all items)."""
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    repo = get_plaid_repo()
    items = await repo.get_items()
    if not user.get("is_owner"):
        items = [i for i in items if i.get("user_id") == int(uid)]
    return [PlaidItem(**i) for i in items]


@router.get("/items/{item_id}/data-summary")
async def get_item_data_summary(item_id: str, request: Request):
    """
    Return counts of transactions and accounts associated with a Plaid item.
    Used by the UI to show a warning before destructive delete + purge.
    """
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    repo = get_plaid_repo()
    row = await repo.get_item(item_id)
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    if not user.get("is_owner") and row.get("user_id") != int(uid):
        raise HTTPException(status_code=403, detail="Not allowed to access this item")
    return await repo.get_item_data_summary(item_id)


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: str,
    request: Request,
    purge: bool = Query(
        False,
        description=(
            "When true, also delete accounts, transactions, recurring streams and "
            "investment holdings imported from this bank. Default keeps historical "
            "data to preserve existing reports, but reconnecting the same bank "
            "will then create duplicate accounts and transactions."
        ),
    ),
):
    """
    Disconnect a bank item.

    * ``purge=false`` (default): remove only the Plaid connection. Imported
      transactions and accounts stay so historical reports are preserved, but
      reconnecting the same bank later will result in duplicate rows because
      Plaid assigns new ``item_id`` / ``account_id`` values on every re-link.
    * ``purge=true``: additionally remove all Plaid-sourced transactions,
      accounts, recurring streams and investment holdings tied to this item.
      Cash and manual transactions are never removed.

    Only the item's owner (or app owner) can delete it.
    """
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    repo = get_plaid_repo()
    row = await repo.get_item(item_id)
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    if not user.get("is_owner") and row.get("user_id") != int(uid):
        raise HTTPException(status_code=403, detail="Not allowed to delete this item")

    if purge:
        summary = await repo.purge_item(item_id)
        if summary.get("plaid_items_deleted", 0) == 0:
            raise HTTPException(status_code=404, detail="Item not found")
        await audit_record(
            "plaid.item_remove",
            source="manual",
            request=request,
            target_kind="plaid_item",
            target_id=item_id,
            metadata={
                "purge": True,
                "institution_name": row.get("institution_name"),
                **{k: summary.get(k) for k in (
                    "transactions_deleted",
                    "accounts_deleted",
                    "recurring_streams_deleted",
                    "plaid_items_deleted",
                ) if k in summary},
            },
        )
        return {"message": "Bank connection and imported data removed", **summary}

    deleted = await repo.delete_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")
    await audit_record(
        "plaid.item_remove",
        source="manual",
        request=request,
        target_kind="plaid_item",
        target_id=item_id,
        metadata={
            "purge": False,
            "institution_name": row.get("institution_name"),
        },
    )
    return {"message": "Bank connection removed"}


@router.post("/items/{item_id}/reset-cursor")
async def reset_cursor(item_id: str, request: Request):
    """Reset sync cursor. Only the item's owner (or app owner) can reset it."""
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    repo = get_plaid_repo()
    row = await repo.get_item(item_id)
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    if not user.get("is_owner") and row.get("user_id") != int(uid):
        raise HTTPException(status_code=403, detail="Not allowed to reset this item")
    ok = await repo.reset_cursor(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found")
    await audit_record(
        "plaid.cursor_reset",
        source="manual",
        request=request,
        target_kind="plaid_item",
        target_id=item_id,
        metadata={"institution_name": row.get("institution_name")},
    )
    return {"message": "Cursor reset. Next sync will re-import all transactions."}


async def _audit_manual_plaid_sync(request: Request, results: List[dict]) -> None:
    """Single audit row for a manual multi-item sync (JSON or NDJSON endpoint)."""
    txn_total = sum(int(r.get("transactions_added") or 0) for r in results)
    balances_total = sum(int(r.get("balances_updated") or 0) for r in results)
    errors = [r for r in results if r.get("status") != "ok"]
    await audit_record(
        "plaid.sync_manual",
        source="manual",
        request=request,
        metadata={
            "items_synced": len(results),
            "transactions_added": txn_total,
            "balances_updated": balances_total,
            "errors": [
                {"item_id": e.get("item_id"), "error": e.get("error_msg")}
                for e in errors
            ],
        },
    )


@router.post("/sync", response_model=List[SyncResult])
async def sync_now(request: Request):
    """Manually trigger synchronization for all connected items."""
    from .scheduler import sync_all_items

    results = await sync_all_items(audit_source="manual")
    await _audit_manual_plaid_sync(request, results)
    return results


@router.post("/sync/stream")
async def sync_now_stream(request: Request):
    """Stream sync progress as NDJSON (one line per item when it completes).

    Each line is ``{"index": 1-based, "total": N, "result": { ... SyncResult }}``.
    The final audit row matches ``POST /api/plaid/sync`` once all items finish.
    """
    from .scheduler import iter_sync_all_items

    async def ndjson_body():
        repo = get_plaid_repo()
        total = len(await repo.get_items())
        results: List[dict] = []
        async for result in iter_sync_all_items(audit_source="manual"):
            results.append(result)
            yield json.dumps(
                {"index": len(results), "total": total, "result": result},
                default=str,
            ) + "\n"
        await _audit_manual_plaid_sync(request, results)

    return StreamingResponse(
        ndjson_body(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sync/log", response_model=List[PlaidSyncLogEntry])
async def get_sync_log():
    """Get the last 50 sync log entries."""
    repo = get_plaid_repo()
    entries = await repo.get_sync_log(limit=50)
    return [PlaidSyncLogEntry(**e) for e in entries]


@router.delete("/sync/log")
async def clear_sync_log(request: Request):
    """Owner-only. Wipe plaid_sync_log and write an audit breadcrumb.

    The sync log is a rolling per-item runs history (errors, counts). It
    can accumulate rows that look alarming to family members long after
    they've been resolved — giving the owner a visible "clear" lets them
    start from a clean slate without needing DB access.
    """
    user = getattr(request.state, "user", None) or {}
    if user.get("id") is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not user.get("is_owner"):
        raise HTTPException(status_code=403, detail="Owner role required")

    repo = get_plaid_repo()
    deleted = await repo.clear_sync_log()
    await audit_record(
        "plaid.sync_log_cleared",
        source="manual",
        request=request,
        metadata={"rows_deleted": deleted},
    )
    return {"deleted": deleted, "cleared_by": user.get("username")}


@router.delete("/sandbox-data")
async def delete_sandbox_data(request: Request):
    """
    Delete all data imported from Plaid sandbox environment.
    Only removes rows with source = 'plaid_sandbox' and their linked accounts/items.
    Manual transactions, categories, tags, and budgets are never touched.
    """
    repo = get_plaid_repo()
    summary = await repo.delete_sandbox_data()
    await audit_record(
        "plaid.sandbox_wiped",
        source="manual",
        request=request,
        metadata=dict(summary),
    )
    return {"message": "Sandbox data deleted", **summary}


@router.post("/webhook")
async def plaid_webhook(request: Request):
    """Plaid webhooks: ITEM_LOGIN_REQUIRED, SYNC_UPDATES_AVAILABLE (JWT verify unless skipped).

    When the in-app webhook toggle is off, we short-circuit with 200 OK *before*
    spending any work — no debounced sync, no Balance call, no DB writes. We
    also unregistered the webhook URL at Plaid when the toggle flipped, so in
    practice these calls stop arriving, but this guard defends against stale
    registrations during the transition window.
    """
    from .webhook_verify import verify_plaid_webhook
    from .scheduler import schedule_debounced_sync_item

    if not await _webhooks_enabled():
        logger.info("Plaid webhook received but toggle is OFF — ignoring")
        return {"status": "disabled"}

    raw = await request.body()
    if not verify_plaid_webhook(request, raw):
        raise HTTPException(status_code=401, detail="Webhook verification failed")
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    repo = get_plaid_repo()
    webhook_id = payload.get("webhook_id")
    if webhook_id and not await repo.try_insert_webhook_event(str(webhook_id)):
        return {"status": "duplicate"}

    wtype = (payload.get("webhook_type") or "").upper()
    wcode = (payload.get("webhook_code") or "").upper()
    item_id = payload.get("item_id")

    if wtype == "ITEM" and wcode == "ITEM_LOGIN_REQUIRED" and item_id:
        await repo.set_item_login_required(str(item_id), True)
    elif wtype == "ITEM" and wcode == "PENDING_DISCONNECT" and item_id:
        # Item will be disconnected soon (e.g. BofA API migration, consent expiry).
        # Flag it as login_required so the UI shows "Fix connection" prompt.
        await repo.set_item_login_required(str(item_id), True)
        logger.warning("PENDING_DISCONNECT received for item %s — user must re-authenticate", item_id)
    elif wtype == "ITEM" and wcode in ("PENDING_EXPIRATION", "USER_PERMISSION_REVOKED") and item_id:
        # OAuth consent is expiring (EU institutions, Capital One, PNC, etc.)
        # or user revoked access at their bank's portal.
        await repo.set_item_login_required(str(item_id), True)
        logger.warning("Webhook %s received for item %s — item flagged for re-auth", wcode, item_id)
    elif wtype == "TRANSACTIONS" and wcode == "SYNC_UPDATES_AVAILABLE" and item_id:
        await repo.set_sync_updates_pending(str(item_id), True)
        schedule_debounced_sync_item(str(item_id))

    return {"status": "ok"}
