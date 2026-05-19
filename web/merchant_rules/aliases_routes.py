"""HTTP surface for merchant aliases (display rename + curated logo).

Mounted under ``/api/merchant-aliases`` (separate router from
``/api/merchant-rules`` to keep the categorization-rule API uncluttered).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from web.enrichment.candidates import LogoCandidate, resolve_logo_candidates

from .aliases import MerchantAliasesRepository

router = APIRouter(prefix="/api/merchant-aliases", tags=["merchant-aliases"])


def _repo() -> MerchantAliasesRepository:
    return MerchantAliasesRepository()


class MerchantAliasUpsert(BaseModel):
    """Body for ``PUT /api/merchant-aliases``.

    At least one of ``merchant_entity_id``, ``merchant_name``, or
    ``merchant_label`` (fallback to ``display_title``) must be provided
    so we can derive the merchant_key. At least one of ``display_name``,
    ``website``, or ``chosen_logo_url`` must be supplied so we have
    something to write.

    Empty-string vs. ``null`` matters: ``null`` means "don't touch this
    field on update"; ``""`` means "clear this field". The repo merges
    accordingly.
    """

    # Identifier trio (at least one required, checked by the validator below)
    merchant_entity_id: Optional[str] = Field(None, max_length=200)
    merchant_name: Optional[str] = Field(None, max_length=500)
    merchant_label: Optional[str] = Field(None, max_length=500)

    # Payload — at least one of these three must be provided.
    display_name: Optional[str] = Field(None, max_length=200)
    website: Optional[str] = Field(None, max_length=500)
    chosen_logo_url: Optional[str] = Field(None, max_length=2000)
    chosen_logo_domain: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def _at_least_one_identifier(self) -> "MerchantAliasUpsert":
        if not any(
            (s or "").strip()
            for s in (self.merchant_entity_id, self.merchant_name, self.merchant_label)
        ):
            raise ValueError(
                "Provide merchant_entity_id, merchant_name, or merchant_label."
            )
        if (
            self.display_name is None
            and self.website is None
            and self.chosen_logo_url is None
        ):
            raise ValueError(
                "Provide at least one of display_name, website, "
                "or chosen_logo_url."
            )
        return self


class MerchantAliasOut(BaseModel):
    merchant_key: str
    display_label: str
    display_name: str
    website: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@router.get("", response_model=List[MerchantAliasOut])
async def list_aliases():
    return await _repo().list_aliases()


@router.put("", response_model=MerchantAliasOut)
async def upsert_alias(body: MerchantAliasUpsert):
    """Create or replace the alias for a merchant. Idempotent.

    Each of ``display_name`` / ``website`` / ``chosen_logo_url`` can be
    updated independently — pass ``null`` to leave the existing value
    alone, pass ``""`` to clear it. ``chosen_logo_url`` is sticky:
    when set, the read-time JOIN renders the user's pick over any
    Plaid/Brandfetch-resolved logo for the same merchant.
    """
    try:
        return await _repo().upsert_alias(
            merchant_entity_id=body.merchant_entity_id,
            merchant_name=body.merchant_name,
            fallback_display=body.merchant_label,
            display_name=body.display_name,
            website=body.website,
            chosen_logo_url=body.chosen_logo_url,
            chosen_logo_domain=body.chosen_logo_domain,
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


class LogoCandidatesOut(BaseModel):
    domain: str
    candidates: List[LogoCandidate]


@router.get("/logo-candidates", response_model=LogoCandidatesOut)
async def logo_candidates(
    domain: str = Query(..., min_length=1, max_length=500,
                        description="Raw user-typed website. Scheme / www. / path optional."),
):
    """Return ready-to-render logo URLs harvested from Brandfetch +
    faviconextractor + Google s2/favicons for a user-supplied domain.

    The UI feeds these into a thumbnail picker; on save it posts the
    chosen URL back via ``PUT /api/merchant-aliases``.

    Best-effort — sources that 404 or time out drop out silently;
    callers should expect an empty list for an invalid or unknown
    domain and degrade gracefully (the existing gradient avatar is
    the right fallback).
    """
    from web.enrichment.candidates import normalize_domain

    normalized = normalize_domain(domain)
    candidates = await resolve_logo_candidates(domain)
    return LogoCandidatesOut(
        domain=normalized or domain.strip(),
        candidates=candidates,
    )
