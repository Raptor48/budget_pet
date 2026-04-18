from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request

from pydantic import BaseModel, Field, model_validator

from .apply import apply_rule_to_transactions, preview_for_draft, preview_for_rule
from .keys import display_merchant_label, merchant_key
from .repo import MerchantRulesRepository

router = APIRouter(prefix="/api/merchant-rules", tags=["merchant-rules"])


def _repo() -> MerchantRulesRepository:
    return MerchantRulesRepository()


class MerchantRuleCreate(BaseModel):
    category_id: int = Field(..., ge=1)
    merchant_entity_id: Optional[str] = Field(None, max_length=200)
    merchant_name: Optional[str] = Field(None, max_length=500)


class MerchantRuleOut(BaseModel):
    id: int
    merchant_key: str
    display_label: str
    category_id: int
    category_name: str


class MerchantRulePreviewBody(BaseModel):
    """When rule_id is set, category_id is ignored (loaded from the rule)."""

    category_id: Optional[int] = Field(None, ge=1)
    rule_id: Optional[int] = Field(None, ge=1)
    merchant_entity_id: Optional[str] = Field(None, max_length=200)
    merchant_name: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def rule_or_merchant(self) -> "MerchantRulePreviewBody":
        if self.rule_id is not None:
            return self
        if self.category_id is None:
            raise ValueError("category_id is required when previewing without rule_id")
        if not self.merchant_entity_id and not self.merchant_name:
            raise ValueError("Provide rule_id or merchant_entity_id or merchant_name")
        return self


class MerchantRulePreviewOut(BaseModel):
    eligible_count: int
    skipped_splits_count: int
    skipped_custom_category_count: int
    skipped_has_entity_id_count: int
    sample_merchant_names: List[str]
    merchant_key: Optional[str] = None
    display_label: Optional[str] = None


class MerchantRuleApplyOut(MerchantRulePreviewOut):
    updated_count: int


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
    if not body.merchant_entity_id and not body.merchant_name:
        raise HTTPException(status_code=422, detail="merchant_entity_id or merchant_name required")
    try:
        row = await _repo().upsert_rule(
            body.merchant_entity_id,
            body.merchant_name,
            body.category_id,
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
            data = await preview_for_rule(rule["merchant_key"], int(rule["category_id"]))
            data["merchant_key"] = rule["merchant_key"]
            data["display_label"] = display_merchant_label(rule["merchant_key"])
        else:
            data = await preview_for_draft(
                body.merchant_entity_id,
                body.merchant_name,
                int(body.category_id),
            )
            mk = merchant_key(body.merchant_entity_id, body.merchant_name)
            if mk:
                data["merchant_key"] = mk
                data["display_label"] = display_merchant_label(mk)
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
