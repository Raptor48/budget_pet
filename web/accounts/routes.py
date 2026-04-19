from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request  # noqa: F401

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


_MANUAL_OVERRIDE_FIELDS = ("credit_limit_cents_manual", "apr_percent_manual")

# Map manual override → Plaid source of truth, for the "bank already
# reports this" guard.
_MANUAL_TO_PLAID_SOURCE = {
    "credit_limit_cents_manual": ("credit_limit_cents", "credit_limit"),
    "apr_percent_manual": ("apr_percent", "APR"),
}


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(account_id: int, body: AccountUpdate, request: Request):
    repo = _repo()
    sent_keys = body.model_fields_set
    # ``exclude_unset`` preserves explicit ``null`` so users can clear a
    # manual override. Other fields keep the ``exclude_none`` behaviour
    # via the ``sent_keys`` filter below.
    raw = body.model_dump(exclude_unset=True)

    # Build the payload for the repo: everything the client sent, dropping
    # ``None`` for non-override fields (they historically meant "do not
    # touch") but keeping it for override fields (where it means "clear").
    payload: dict = {}
    for k, v in raw.items():
        if k in _MANUAL_OVERRIDE_FIELDS:
            payload[k] = v  # may be None
        elif v is not None:
            payload[k] = v

    # Authorize and validate against the current DB state for anything
    # that needs it. We only load the row when needed.
    acct: Optional[dict] = None
    needs_acct = ("current_balance_cents" in sent_keys) or any(
        k in sent_keys for k in _MANUAL_OVERRIDE_FIELDS
    )
    if needs_acct:
        acct = await repo.get_account(account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")

    user = getattr(request.state, "user", None) or {}
    current_id = user.get("id")
    is_owner = bool(user.get("is_owner"))

    if "current_balance_cents" in sent_keys and acct is not None:
        if not is_designated_cash_wallet(acct):
            raise HTTPException(
                status_code=422,
                detail="current_balance_cents can only be set on the designated Cash wallet",
            )
        owner_id = acct.get("user_id")
        if owner_id is not None and current_id is not None and owner_id != current_id:
            raise HTTPException(status_code=403, detail="Cannot update this account")

    # Manual override guard: same-owner OR platform owner, AND the bank
    # must not already be reporting the value. Clearing (``None``) skips
    # the bank guard so users can always walk back a stale manual number.
    override_keys = [k for k in _MANUAL_OVERRIDE_FIELDS if k in sent_keys]
    if override_keys and acct is not None:
        owner_id = acct.get("user_id")
        if not is_owner and owner_id is not None and owner_id != current_id:
            raise HTTPException(
                status_code=403,
                detail="Cannot update this account",
            )
        for key in override_keys:
            if raw.get(key) is None:
                continue
            plaid_col, pretty = _MANUAL_TO_PLAID_SOURCE[key]
            if acct.get(plaid_col) is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Bank already reports {pretty}; manual override "
                        "is disabled. Clear the field to fall back to the "
                        "bank-reported value."
                    ),
                )

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
