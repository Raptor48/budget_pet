"""
FastAPI routes for Plaid integration — V2.
"""
import json
import logging
from typing import List

from fastapi import APIRouter, Body, HTTPException, Request

from .client import (
    create_link_token,
    exchange_public_token,
    get_institution_metadata,
    get_item_institution_id,
)
from .models import ExchangeTokenRequest, LinkTokenBody, LinkTokenResponse, PlaidItem, PlaidSyncLogEntry, SyncResult
from .repo import get_plaid_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plaid", tags=["plaid"])


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
        result = create_link_token(user_id=str(uid), access_token=access_token)
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


@router.delete("/items/{item_id}")
async def delete_item(item_id: str, request: Request):
    """Disconnect a bank item. Only the item's owner (or app owner) can delete it."""
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
    deleted = await repo.delete_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")
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
    return {"message": "Cursor reset. Next sync will re-import all transactions."}


@router.post("/sync", response_model=List[SyncResult])
async def sync_now():
    """Manually trigger synchronization for all connected items."""
    from .scheduler import sync_all_items
    results = await sync_all_items()
    return results


@router.get("/sync/log", response_model=List[PlaidSyncLogEntry])
async def get_sync_log():
    """Get the last 50 sync log entries."""
    repo = get_plaid_repo()
    entries = await repo.get_sync_log(limit=50)
    return [PlaidSyncLogEntry(**e) for e in entries]


@router.delete("/sandbox-data")
async def delete_sandbox_data():
    """
    Delete all data imported from Plaid sandbox environment.
    Only removes rows with source = 'plaid_sandbox' and their linked accounts/items.
    Manual transactions, categories, tags, and budgets are never touched.
    """
    repo = get_plaid_repo()
    summary = await repo.delete_sandbox_data()
    return {"message": "Sandbox data deleted", **summary}


@router.post("/webhook")
async def plaid_webhook(request: Request):
    """Plaid webhooks: ITEM_LOGIN_REQUIRED, SYNC_UPDATES_AVAILABLE (JWT verify unless skipped)."""
    from .webhook_verify import verify_plaid_webhook
    from .scheduler import schedule_debounced_sync_item

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
