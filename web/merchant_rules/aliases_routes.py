"""HTTP surface for merchant aliases (display rename).

Mounted under ``/api/merchant-aliases`` (separate router from
``/api/merchant-rules`` to keep the categorization-rule API uncluttered).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from .aliases import MerchantAliasesRepository

router = APIRouter(prefix="/api/merchant-aliases", tags=["merchant-aliases"])


def _repo() -> MerchantAliasesRepository:
    return MerchantAliasesRepository()


class MerchantAliasUpsert(BaseModel):
    """Body for ``PUT /api/merchant-aliases``.

    At least one of ``merchant_entity_id``, ``merchant_name``, or
    ``merchant_label`` (fallback to ``display_title``) must be provided so we
    can derive the merchant_key. ``display_name`` is the chosen rename and
    must be non-empty.
    """

    display_name: str = Field(..., min_length=1, max_length=200)
    merchant_entity_id: Optional[str] = Field(None, max_length=200)
    merchant_name: Optional[str] = Field(None, max_length=500)
    merchant_label: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def _at_least_one_identifier(self) -> "MerchantAliasUpsert":
        # Earlier draft accidentally compared ``self.merchant_entity_id``
        # in every branch instead of the loop variable, so a perfectly
        # valid {merchant_entity_id: null, merchant_name: "Nyflower"}
        # was rejected as 422 ("Provide ..."). The straightforward
        # generator below treats all three identifiers symmetrically.
        if not any(
            (s or "").strip()
            for s in (self.merchant_entity_id, self.merchant_name, self.merchant_label)
        ):
            raise ValueError(
                "Provide merchant_entity_id, merchant_name, or merchant_label."
            )
        return self


class MerchantAliasOut(BaseModel):
    merchant_key: str
    display_label: str
    display_name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@router.get("", response_model=List[MerchantAliasOut])
async def list_aliases():
    return await _repo().list_aliases()


@router.put("", response_model=MerchantAliasOut)
async def upsert_alias(body: MerchantAliasUpsert):
    """Create or replace the alias for a merchant.

    Idempotent: re-PUTting with a different ``display_name`` overwrites and
    bumps ``updated_at``. ``display_name`` is trimmed; an empty result is
    rejected (use DELETE to remove an alias).
    """
    try:
        return await _repo().upsert_alias(
            merchant_entity_id=body.merchant_entity_id,
            merchant_name=body.merchant_name,
            fallback_display=body.merchant_label,
            display_name=body.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


class MerchantAliasDeleteBody(BaseModel):
    """Either ``merchant_key`` directly (preferred) or the merchant attribute
    trio so the server re-derives it.
    """

    merchant_key: Optional[str] = Field(None, max_length=600)
    merchant_entity_id: Optional[str] = Field(None, max_length=200)
    merchant_name: Optional[str] = Field(None, max_length=500)
    merchant_label: Optional[str] = Field(None, max_length=500)


@router.post("/delete", status_code=204)
async def delete_alias(body: MerchantAliasDeleteBody):
    """POST + body instead of DELETE because some hosts strip DELETE bodies
    and the merchant identifiers don't fit cleanly in a path or query string
    (raw merchant_name can contain ``/``, ``#``, etc).
    """
    ok = await _repo().delete_alias(
        merchant_key=body.merchant_key,
        merchant_entity_id=body.merchant_entity_id,
        merchant_name=body.merchant_name,
        fallback_display=body.merchant_label,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Alias not found")
    return None
