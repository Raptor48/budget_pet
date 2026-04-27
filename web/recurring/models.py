from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class RecurringStreamCreate(BaseModel):
    account_id: int = Field(..., ge=1)
    direction: str = Field(..., pattern=r"^(inflow|outflow)$")
    description: str = Field(..., min_length=1, max_length=500)
    merchant_name: Optional[str] = Field(None, max_length=500)
    frequency: Optional[str] = Field(None, max_length=80)
    average_amount_cents: int
    last_amount_cents: Optional[int] = None
    currency: str = Field(default="USD", max_length=8)
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    category_id: Optional[int] = None


class RecurringStreamOut(BaseModel):
    id: int
    plaid_stream_id: str
    account_id: Optional[int] = None
    direction: str
    description: str
    merchant_name: Optional[str] = None
    frequency: Optional[str] = None
    average_amount_cents: Optional[int] = None
    last_amount_cents: Optional[int] = None
    currency: str = "USD"
    pfc_primary: Optional[str] = None
    pfc_detailed: Optional[str] = None
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    is_active: bool = True
    status: Optional[str] = None
    category_id: Optional[int] = None
    user_label: Optional[str] = None
    price_change_pct: Optional[Decimal] = None
    last_synced_at: Optional[datetime] = None
    stream_source: str = "plaid"

    # User-managed lifecycle (V2.3). Plaid does not let third-party
    # subscriptions be cancelled via API — these flags mark the local
    # intent so the stream is excluded from KPIs / Insights.
    user_status: str = "active"
    paused_until: Optional[date] = None
    cancelled_at: Optional[datetime] = None
    price_change_snoozed_until: Optional[date] = None

    # ------------------------------------------------------------------
    # Enrichment fields (populated by list_streams via JOINs).
    # None when the row is loaded without enrichment (older code paths).
    # ------------------------------------------------------------------
    account_name: Optional[str] = None
    account_mask: Optional[str] = None
    owner_username: Optional[str] = None
    primary_category_id: Optional[int] = None
    primary_category_name: Optional[str] = None
    primary_category_color: Optional[str] = None
    display_title: Optional[str] = None
    # User-chosen rename for the underlying merchant; layered onto
    # display_title at read time. Keyed by the merchant_name path because
    # Plaid's recurring endpoint does not surface merchant_entity_id.
    merchant_alias: Optional[str] = None

    class Config:
        from_attributes = True


class RecurringStreamUpdate(BaseModel):
    user_label: Optional[str] = Field(None, max_length=200)
    category_id: Optional[int] = None
    user_status: Optional[str] = Field(None, pattern=r"^(active|paused|cancelled)$")
    paused_until: Optional[date] = None
    price_change_snoozed_until: Optional[date] = None


class RecurringBulkAction(BaseModel):
    """Apply one action to many streams at once.

    Actions:
        ``cancel``   — flip user_status='cancelled', stamp cancelled_at=NOW().
        ``pause``    — flip user_status='paused' (optional ``paused_until``).
        ``reactivate`` — flip user_status='active' (clears pause/cancel meta).
        ``snooze_price_change`` — set ``price_change_snoozed_until`` to today
                                  + ``snooze_days`` (default 30).
    """

    ids: List[int] = Field(..., min_length=1, max_length=200)
    action: str = Field(..., pattern=r"^(cancel|pause|reactivate|snooze_price_change)$")
    paused_until: Optional[date] = None
    snooze_days: Optional[int] = Field(None, ge=1, le=365)


class RecurringBulkResult(BaseModel):
    updated: int
