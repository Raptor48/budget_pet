from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from web.accounts.cash_wallet import is_designated_cash_wallet

from .models import AccountCreate, AccountOut, AccountUpdate
from .repo import AccountsRepository

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _repo() -> AccountsRepository:
    return AccountsRepository()


@router.get("", response_model=List[AccountOut])
async def list_accounts(active_only: bool = Query(True)):
    return await _repo().list_accounts(active_only=active_only)


@router.get("/cash-wallet", response_model=AccountOut)
async def get_cash_wallet(request: Request):
    """Lazily create the per-user manual Cash wallet (no Plaid link)."""
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await _repo().ensure_cash_wallet(int(uid))


@router.post("", response_model=AccountOut, status_code=201)
async def create_account(body: AccountCreate):
    return await _repo().create_account(body.model_dump())


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(account_id: int):
    acct = await _repo().get_account(account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")
    return acct


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(account_id: int, body: AccountUpdate, request: Request):
    repo = _repo()
    payload = body.model_dump(exclude_none=True)
    if "current_balance_cents" in payload:
        acct = await repo.get_account(account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        if not is_designated_cash_wallet(acct):
            raise HTTPException(
                status_code=422,
                detail="current_balance_cents can only be set on the designated Cash wallet",
            )
        user = getattr(request.state, "user", None) or {}
        current_id = user.get("id")
        owner_id = acct.get("user_id")
        if owner_id is not None and current_id is not None and owner_id != current_id:
            raise HTTPException(status_code=403, detail="Cannot update this account")
    updated = await repo.update_account(account_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Account not found")
    return updated


@router.delete("/{account_id}", status_code=204)
async def delete_account(account_id: int, request: Request):
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    repo = _repo()
    acct = await repo.get_account(account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")
    if not user.get("is_owner") and acct.get("user_id") is not None and acct.get("user_id") != uid:
        raise HTTPException(status_code=403, detail="Not allowed to delete this account")
    ok = await repo.delete_account(account_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Account not found")
