"""
FastAPI routes for Plaid integration.
"""
import logging
from typing import List
from fastapi import APIRouter, HTTPException

from .client import create_link_token, exchange_public_token, get_transactions_sync, get_account_balances
from .repo import get_plaid_repo
from .models import (
    LinkTokenResponse, ExchangeTokenRequest, PlaidItem,
    PlaidSyncLogEntry, PlaidCategoryMapEntry, PlaidCategoryMapUpdate, SyncResult
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plaid", tags=["plaid"])


@router.post("/link-token", response_model=LinkTokenResponse)
async def get_link_token():
    """Create a Plaid Link token to initialise the Plaid Link UI on the frontend."""
    try:
        result = create_link_token()
        return LinkTokenResponse(**result)
    except Exception as e:
        logger.error("Failed to create link token: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create link token: {e}")


@router.post("/exchange-token", response_model=PlaidItem)
async def exchange_token(body: ExchangeTokenRequest):
    """Exchange Plaid public_token for permanent access_token and save the connection."""
    try:
        tokens = exchange_public_token(body.public_token)
        repo = get_plaid_repo()
        item = await repo.save_item(
            item_id=tokens["item_id"],
            access_token=tokens["access_token"],
            institution_name=body.institution_name,
        )
        return PlaidItem(**item)
    except Exception as e:
        logger.error("Failed to exchange token: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to exchange token: {e}")


@router.get("/items", response_model=List[PlaidItem])
async def list_items():
    """List all connected bank items."""
    repo = get_plaid_repo()
    items = await repo.get_items()
    return [PlaidItem(**i) for i in items]


@router.delete("/items/{item_id}")
async def delete_item(item_id: str):
    """Disconnect a bank item."""
    repo = get_plaid_repo()
    deleted = await repo.delete_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Bank connection removed"}


@router.post("/items/{item_id}/reset-cursor")
async def reset_cursor(item_id: str):
    """Reset sync cursor for an item so the next sync re-imports all transactions."""
    repo = get_plaid_repo()
    ok = await repo.reset_cursor(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Cursor reset. Next sync will re-import all transactions."}


@router.post("/sync", response_model=List[SyncResult])
async def sync_now():
    """Manually trigger synchronisation for all connected items."""
    from .scheduler import sync_all_items
    results = await sync_all_items()
    return results


@router.get("/sync/log", response_model=List[PlaidSyncLogEntry])
async def get_sync_log():
    """Get the last 50 sync log entries."""
    repo = get_plaid_repo()
    entries = await repo.get_sync_log(limit=50)
    return [PlaidSyncLogEntry(**e) for e in entries]


@router.get("/category-map", response_model=List[PlaidCategoryMapEntry])
async def get_category_map():
    """Get current Plaid → budget category mappings."""
    repo = get_plaid_repo()
    mapping = await repo.get_category_map()
    return [PlaidCategoryMapEntry(plaid_category=k, budget_category=v) for k, v in mapping.items()]


@router.patch("/category-map")
async def update_category_map(body: PlaidCategoryMapUpdate):
    """Update Plaid → budget category mappings."""
    repo = get_plaid_repo()
    await repo.upsert_category_mappings([m.dict() for m in body.mappings])
    return {"message": f"Updated {len(body.mappings)} mappings"}
