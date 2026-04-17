from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request

from pydantic import BaseModel, Field

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
    category_id: int
    category_name: str


@router.get("", response_model=List[MerchantRuleOut])
async def list_rules(request: Request):
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    rows = await _repo().list_rules(int(uid))
    return [MerchantRuleOut(**r) for r in rows]


@router.post("", response_model=MerchantRuleOut)
async def create_rule(request: Request, body: MerchantRuleCreate):
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not body.merchant_entity_id and not body.merchant_name:
        raise HTTPException(status_code=422, detail="merchant_entity_id or merchant_name required")
    try:
        row = await _repo().upsert_rule(
            int(uid),
            body.merchant_entity_id,
            body.merchant_name,
            body.category_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MerchantRuleOut(**row)


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, request: Request):
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    ok = await _repo().delete_rule(int(uid), rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True}
