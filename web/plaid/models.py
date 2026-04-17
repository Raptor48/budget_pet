"""
Pydantic models for Plaid integration — V2.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class PlaidItem(BaseModel):
    item_id: str
    institution_name: Optional[str] = None
    institution_color: Optional[str] = None
    institution_logo: Optional[str] = None
    user_id: Optional[int] = None
    cursor: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    connected_at: Optional[datetime] = None
    item_login_required: bool = False
    sync_updates_pending: bool = False

    class Config:
        from_attributes = True


class LinkTokenBody(BaseModel):
    """Optional `item_id` for Plaid Link update mode (uses stored access_token)."""

    item_id: Optional[str] = None


class PlaidSyncLogEntry(BaseModel):
    id: int
    item_id: str
    synced_at: datetime
    transactions_added: int
    balances_updated: int
    status: str
    error_msg: Optional[str] = None

    class Config:
        from_attributes = True


class ExchangeTokenRequest(BaseModel):
    public_token: str
    institution_name: Optional[str] = None


class SyncResult(BaseModel):
    item_id: str
    transactions_added: int
    balances_updated: int
    status: str
    error_msg: Optional[str] = None


class LinkTokenResponse(BaseModel):
    link_token: str
    expiration: str
