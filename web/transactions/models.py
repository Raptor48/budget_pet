from datetime import date
from datetime import datetime as DateTime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TagBrief(BaseModel):
    id: int
    name: str
    color: str

    class Config:
        from_attributes = True


class TransactionDateRange(BaseModel):
    """Earliest / latest transaction months visible to the caller (YYYY-MM)."""

    min_month: Optional[str] = None
    max_month: Optional[str] = None
    earliest: Optional[date] = None
    latest: Optional[date] = None


class SplitOut(BaseModel):
    id: int
    parent_transaction_id: int
    category_id: Optional[int] = None
    tag_id: Optional[int] = None
    amount_cents: int
    note: Optional[str] = None
    created_at: Optional[DateTime] = None

    class Config:
        from_attributes = True


TransactionClassLiteral = Literal["income", "expense", "internal_transfer", "uncategorized"]


class TransactionOut(BaseModel):
    id: int
    plaid_transaction_id: Optional[str] = None
    account_id: int
    category_id: Optional[int] = None
    amount_cents: int
    currency: str = "USD"
    date: date
    authorized_date: Optional[date] = None
    datetime: Optional[DateTime] = None
    authorized_datetime: Optional[DateTime] = None
    name: str
    merchant_name: Optional[str] = None
    merchant_entity_id: Optional[str] = None
    logo_url: Optional[str] = None
    website: Optional[str] = None
    payment_channel: Optional[str] = None
    pfc_primary: Optional[str] = None
    pfc_detailed: Optional[str] = None
    pfc_confidence: Optional[str] = None
    pfc_icon_url: Optional[str] = None
    counterparties: Optional[Any] = None
    location: Optional[Any] = None
    payment_meta: Optional[Any] = None
    is_pending: bool = False
    is_private: bool = False
    is_internal_transfer: bool = False
    is_internal_transfer_manual: bool = False
    # The canonical four-class classification (see docs/reports-math.md).
    # Written by ``web.classification.classifier`` on insert and on every
    # rescan. Defaults to ``'uncategorized'`` for rows whose migration has
    # not yet run.
    transaction_class: TransactionClassLiteral = "uncategorized"
    # When the user explicitly forces a class on a single row, the value
    # lives here and always wins over the auto-classifier.
    manual_class_override: Optional[TransactionClassLiteral] = None
    source: str = "manual"
    user_note: Optional[str] = None
    created_at: Optional[DateTime] = None
    updated_at: Optional[DateTime] = None
    tags: List[TagBrief] = []
    has_splits: bool = False
    splits: List[SplitOut] = []
    # Joined from accounts table
    account_name: Optional[str] = None
    account_mask: Optional[str] = None
    # Joined from users via accounts.user_id
    owner_username: Optional[str] = None
    # Derived display title — short, human-friendly. See web/transactions/display.py.
    display_title: Optional[str] = None

    class Config:
        from_attributes = True


class TransactionCreate(BaseModel):
    """Manual cash transaction — posted to the user's Cash wallet; `source` and defaults are set by the route."""

    model_config = ConfigDict(extra="ignore")

    amount_cents: int
    date: date
    name: str = Field(..., min_length=1, max_length=500)
    category_id: Optional[int] = None
    authorized_date: Optional[date] = None
    merchant_name: Optional[str] = None
    user_note: Optional[str] = None

    @field_validator("amount_cents")
    @classmethod
    def amount_nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("amount_cents must not be zero")
        return v


class TransactionUpdate(BaseModel):
    """Fields the user can PATCH on an existing transaction.

    ``transaction_class`` is the preferred knob: ``'internal_transfer'`` to
    exclude the row from income/expense aggregates, ``'income'`` /
    ``'expense'`` to force a class, ``None`` / omitted to restore auto
    classification. The legacy ``is_internal_transfer`` boolean remains
    accepted for older clients; both paths set ``manual_class_override``
    under the hood so user intent survives the next auto rescan.
    """

    model_config = ConfigDict(extra="ignore")

    category_id: Optional[int] = None
    user_note: Optional[str] = None
    merchant_name: Optional[str] = None
    is_private: Optional[bool] = None
    is_internal_transfer: Optional[bool] = None
    transaction_class: Optional[TransactionClassLiteral] = None


class SplitCreate(BaseModel):
    category_id: Optional[int] = None
    tag_id: Optional[int] = None
    amount_cents: int = Field(..., ne=0)
    note: Optional[str] = None


class SplitListCreate(BaseModel):
    splits: List[SplitCreate] = Field(..., min_length=2)
