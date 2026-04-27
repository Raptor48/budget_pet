from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request

from pydantic import BaseModel, Field, model_validator

from .apply import (
    apply_rule_to_transactions,
    preview_for_draft,
    preview_for_rule,
    preview_match_count,
)
from .keys import display_merchant_label, merchant_key
from .repo import MerchantRulesRepository

router = APIRouter(prefix="/api/merchant-rules", tags=["merchant-rules"])


def _repo() -> MerchantRulesRepository:
    return MerchantRulesRepository()


class MerchantRuleCreate(BaseModel):
    """
    ``merchant_label`` is the fallback used for transactions without a Plaid
    merchant (ACH / checks / bill pays). It should be the caller's view of the
    merchant — normally the transaction's ``display_title``. Only consulted
    when both ``merchant_entity_id`` and ``merchant_name`` are blank.

    ``description_contains`` (optional) narrows the rule to transactions
    whose ``name`` (raw statement line) or ``display_title`` contains the
    given substring (case-insensitive). When set, this rule wins over a
    generic rule on the same ``merchant_key``. See
    ``docs/categorization-precedence.md`` §3.
    """

    category_id: int = Field(..., ge=1)
    merchant_entity_id: Optional[str] = Field(None, max_length=200)
    merchant_name: Optional[str] = Field(None, max_length=500)
    merchant_label: Optional[str] = Field(None, max_length=500)
    description_contains: Optional[str] = Field(None, max_length=200)


class MerchantRuleOut(BaseModel):
    id: int
    merchant_key: str
    display_label: str
    category_id: int
    category_name: str
    description_contains: Optional[str] = None


class MerchantRulePreviewBody(BaseModel):
    """
    Three call shapes supported:
      1. ``rule_id`` only — preview a saved rule (``category_id`` ignored).
      2. ``merchant_*`` + ``category_id`` — full draft preview with
         eligible/skipped buckets.
      3. ``merchant_*`` without ``category_id`` — lightweight match-count
         preview used while the user is still typing.

    Any of the three shapes may include ``description_contains`` to narrow
    the match further. Pass ``None`` (default) to preview the existing
    "match every transaction with this merchant_key" behavior.
    """

    category_id: Optional[int] = Field(None, ge=1)
    rule_id: Optional[int] = Field(None, ge=1)
    merchant_entity_id: Optional[str] = Field(None, max_length=200)
    merchant_name: Optional[str] = Field(None, max_length=500)
    merchant_label: Optional[str] = Field(None, max_length=500)
    description_contains: Optional[str] = Field(None, max_length=200)

    @model_validator(mode="after")
    def rule_or_merchant(self) -> "MerchantRulePreviewBody":
        if self.rule_id is not None:
            return self
        if not (self.merchant_entity_id or self.merchant_name or self.merchant_label):
            raise ValueError("Provide rule_id or merchant_entity_id/merchant_name/merchant_label")
        return self


class MerchantRulePreviewOut(BaseModel):
    eligible_count: Optional[int] = None
    skipped_splits_count: Optional[int] = None
    skipped_custom_category_count: Optional[int] = None
    skipped_has_entity_id_count: Optional[int] = None
    sample_merchant_names: List[str] = []
    match_count: Optional[int] = None
    # Total number of distinct ``name`` values for this merchant in the
    # table (ignores ``description_contains``). UI uses this to decide
    # whether to surface the "narrow with description" affordance.
    distinct_description_count: Optional[int] = None
    merchant_key: Optional[str] = None
    display_label: Optional[str] = None


class MerchantRuleApplyOut(MerchantRulePreviewOut):
    updated_count: int = 0
    description_contains: Optional[str] = None


@router.get("", response_model=List[MerchantRuleOut])
async def list_rules(request: Request):
    user = getattr(request.state, "user", None) or {}
    if user.get("id") is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    rows = await _repo().list_rules()
    return [MerchantRuleOut(**r) for r in rows]


@router.post("", response_model=MerchantRuleOut)
async def create_rule(request: Request, body: MerchantRuleCreate):
    user = getattr(request.state, "user", None) or {}
    if user.get("id") is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not (body.merchant_entity_id or body.merchant_name or body.merchant_label):
        raise HTTPException(
            status_code=422,
            detail="merchant_entity_id, merchant_name, or merchant_label required",
        )
    try:
        row = await _repo().upsert_rule(
            body.merchant_entity_id,
            body.merchant_name,
            body.category_id,
            body.merchant_label,
            description_contains=body.description_contains,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MerchantRuleOut(**row)


@router.post("/preview", response_model=MerchantRulePreviewOut)
async def preview_merchant_rule(request: Request, body: MerchantRulePreviewBody):
    user = getattr(request.state, "user", None) or {}
    if user.get("id") is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        if body.rule_id is not None:
            rule = await _repo().get_rule(int(body.rule_id))
            if not rule:
                raise HTTPException(status_code=404, detail="Rule not found")
            data = await preview_for_rule(
                rule["merchant_key"],
                int(rule["category_id"]),
                description_contains=rule.get("description_contains"),
            )
            data["merchant_key"] = rule["merchant_key"]
            data["display_label"] = display_merchant_label(rule["merchant_key"])
        elif body.category_id is not None:
            data = await preview_for_draft(
                body.merchant_entity_id,
                body.merchant_name or body.merchant_label,
                int(body.category_id),
                description_contains=body.description_contains,
            )
            mk = merchant_key(
                body.merchant_entity_id, body.merchant_name, body.merchant_label
            )
            if mk:
                data["merchant_key"] = mk
                data["display_label"] = display_merchant_label(mk)
        else:
            # Category-less "how many transactions match?" preview.
            data = await preview_match_count(
                body.merchant_entity_id,
                body.merchant_name or body.merchant_label,
                description_contains=body.description_contains,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MerchantRulePreviewOut(**data)


@router.post("/{rule_id}/apply-existing", response_model=MerchantRuleApplyOut)
async def apply_existing(rule_id: int, request: Request):
    user = getattr(request.state, "user", None) or {}
    if user.get("id") is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        data = await apply_rule_to_transactions(rule_id)
    except ValueError as exc:
        if str(exc) == "Rule not found":
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MerchantRuleApplyOut(**data)


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, request: Request):
    user = getattr(request.state, "user", None) or {}
    if user.get("id") is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    ok = await _repo().delete_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True}
