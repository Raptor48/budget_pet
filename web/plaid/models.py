"""
Pydantic models for Plaid integration.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class PlaidItem(BaseModel):
    id: int
    item_id: str
    institution_name: Optional[str] = None
    connected_at: datetime
    last_synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


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


class PlaidCategoryMapEntry(BaseModel):
    plaid_category: str
    budget_category: str


class PlaidCategoryMapUpdate(BaseModel):
    mappings: List[PlaidCategoryMapEntry]


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
