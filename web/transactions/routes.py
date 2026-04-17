import csv
import io
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .models import (
    SplitListCreate,
    SplitOut,
    TransactionCreate,
    TransactionOut,
    TransactionUpdate,
)
from web.env_flags import reports_include_plaid_sandbox

from web.accounts.repo import AccountsRepository

from .repo import TransactionsRepository
from .splits_repo import SplitsRepository

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


def _repo() -> TransactionsRepository:
    return TransactionsRepository()


def _splits() -> SplitsRepository:
    return SplitsRepository()


async def _enrich(txn: dict, repo: TransactionsRepository) -> dict:
    """Attach tags and splits to a transaction dict."""
    txn["tags"] = await repo.get_tags_for_transaction(txn["id"])
    txn["splits"] = await repo.get_splits_for_transaction(txn["id"])
    return txn


async def _enrich_many(rows: List[Dict[str, Any]], repo: TransactionsRepository) -> List[Dict[str, Any]]:
    """Attach tags and splits for many transactions (two queries total)."""
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    tags_map = await repo.get_tags_for_transaction_ids(ids)
    splits_map = await repo.get_splits_for_transaction_ids(ids)
    for txn in rows:
        tid = txn["id"]
        txn["tags"] = tags_map.get(tid, [])
        txn["splits"] = splits_map.get(tid, [])
    return rows


@router.get("", response_model=List[TransactionOut])
async def list_transactions(
    request: Request,
    month: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}$"),
    account_id: Optional[int] = Query(None),
    category_id: Optional[int] = Query(None),
    tag_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None, max_length=100),
    channel: Optional[str] = Query(None),
    pending_only: Optional[bool] = Query(None),
    source: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    current_user = getattr(request.state, "user", None) or {}
    current_id = current_user.get("id")
    # Non-owners can only access their own transactions; ignore any supplied user_id.
    if not current_user.get("is_owner"):
        user_id = current_id
    repo = _repo()
    rows = await repo.list_transactions(
        month=month,
        account_id=account_id,
        category_id=category_id,
        tag_id=tag_id,
        search=search,
        channel=channel,
        pending_only=pending_only,
        source=source,
        user_id=user_id,
        limit=limit,
        offset=offset,
        omit_heavy_fields=True,
    )
    return await _enrich_many(rows, repo)


@router.post("", response_model=TransactionOut, status_code=201)
async def create_transaction(request: Request, body: TransactionCreate):
    """Create a manual cash transaction (`source=cash`) on the user's Cash wallet."""
    user = getattr(request.state, "user", None) or {}
    current_id = user.get("id")
    if current_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    wallet = await AccountsRepository().ensure_cash_wallet(int(current_id))
    if not wallet.get("is_active"):
        raise HTTPException(status_code=400, detail="Cash wallet is inactive")

    data = body.model_dump()
    data["account_id"] = wallet["id"]
    data["source"] = "cash"
    data["payment_channel"] = "other"
    data["currency"] = "USD"
    data["is_pending"] = False

    repo = _repo()
    try:
        txn = await repo.create_cash_transaction(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return await _enrich(txn, repo)


@router.get("/export")
async def export_transactions(
    request: Request,
    month: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}$"),
    account_id: Optional[int] = Query(None),
    category_id: Optional[int] = Query(None),
    tag_id: Optional[int] = Query(None),
    source: Optional[str] = Query(None),
):
    """Export transactions as CSV. Splits become individual rows."""
    current_user = getattr(request.state, "user", None) or {}
    current_id = current_user.get("id")
    export_user_id = None if current_user.get("is_owner") else current_id
    repo = _repo()
    rows = await repo.list_transactions(
        month=month,
        account_id=account_id,
        category_id=category_id,
        tag_id=tag_id,
        source=source,
        user_id=export_user_id,
        limit=10000,
        omit_heavy_fields=True,
        exclude_plaid_sandbox=not reports_include_plaid_sandbox(),
    )
    await _enrich_many(rows, repo)

    output = io.StringIO()
    fieldnames = [
        "id", "date", "authorized_date", "merchant_name", "name",
        "amount_cents", "amount", "currency", "category_id", "tags",
        "account_id", "payment_channel", "user_note", "is_pending",
        "source", "split_note", "parent_id",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for txn in rows:
        tag_names = ",".join(t["name"] for t in txn.get("tags", []))
        base = {
            "id": txn["id"],
            "date": txn["date"],
            "authorized_date": txn.get("authorized_date", ""),
            "merchant_name": txn.get("merchant_name", ""),
            "name": txn["name"],
            "currency": txn.get("currency", "USD"),
            "category_id": txn.get("category_id", ""),
            "tags": tag_names,
            "account_id": txn["account_id"],
            "payment_channel": txn.get("payment_channel", ""),
            "user_note": txn.get("user_note", ""),
            "is_pending": txn.get("is_pending", False),
            "source": txn.get("source", ""),
            "split_note": "",
            "parent_id": "",
        }
        splits = txn.get("splits", [])
        if splits:
            for s in splits:
                row = {**base}
                row["amount_cents"] = s["amount_cents"]
                row["amount"] = s["amount_cents"] / 100
                row["category_id"] = s.get("category_id") or ""
                row["split_note"] = s.get("note") or ""
                row["parent_id"] = txn["id"]
                row["id"] = s["id"]
                writer.writerow(row)
        else:
            base["amount_cents"] = txn["amount_cents"]
            base["amount"] = txn["amount_cents"] / 100
            writer.writerow(base)

    output.seek(0)
    filename = f"transactions{'-' + month if month else ''}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _check_txn_ownership(txn: dict, current_user: dict) -> None:
    """Raise 403 if the current non-owner user does not own the transaction's account."""
    if current_user.get("is_owner"):
        return
    owner_uid = txn.get("owner_username")
    current_uname = current_user.get("username")
    if owner_uid is not None and current_uname is not None and owner_uid != current_uname:
        raise HTTPException(status_code=403, detail="Not allowed to access this transaction")


@router.get("/{transaction_id}", response_model=TransactionOut)
async def get_transaction(transaction_id: int, request: Request):
    current_user = getattr(request.state, "user", None) or {}
    repo = _repo()
    txn = await repo.get_transaction(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _check_txn_ownership(txn, current_user)
    return await _enrich(txn, repo)


@router.patch("/{transaction_id}", response_model=TransactionOut)
async def update_transaction(transaction_id: int, body: TransactionUpdate, request: Request):
    current_user = getattr(request.state, "user", None) or {}
    repo = _repo()
    txn = await repo.get_transaction(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _check_txn_ownership(txn, current_user)
    updated = await repo.update_transaction(transaction_id, body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return await _enrich(updated, repo)


@router.delete("/{transaction_id}", status_code=204)
async def delete_transaction(transaction_id: int, request: Request):
    current_user = getattr(request.state, "user", None) or {}
    repo = _repo()
    txn = await repo.get_transaction(transaction_id)
    if not txn:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found or cannot be deleted (Plaid-sourced only)",
        )
    _check_txn_ownership(txn, current_user)
    ok = await repo.delete_transaction(transaction_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found or cannot be deleted (Plaid-sourced only)",
        )


@router.post("/{transaction_id}/tags/{tag_id}", status_code=204)
async def add_tag(transaction_id: int, tag_id: int, request: Request):
    current_user = getattr(request.state, "user", None) or {}
    repo = _repo()
    txn = await repo.get_transaction(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _check_txn_ownership(txn, current_user)
    await repo.add_tag(transaction_id, tag_id)


@router.delete("/{transaction_id}/tags/{tag_id}", status_code=204)
async def remove_tag(transaction_id: int, tag_id: int, request: Request):
    current_user = getattr(request.state, "user", None) or {}
    repo = _repo()
    txn = await repo.get_transaction(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _check_txn_ownership(txn, current_user)
    ok = await repo.remove_tag(transaction_id, tag_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Tag not assigned to this transaction")


@router.get("/{transaction_id}/splits", response_model=List[SplitOut])
async def get_splits(transaction_id: int, request: Request):
    current_user = getattr(request.state, "user", None) or {}
    txn = await _repo().get_transaction(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _check_txn_ownership(txn, current_user)
    return await _splits().get_splits(transaction_id)


@router.post("/{transaction_id}/splits", response_model=List[SplitOut])
async def set_splits(transaction_id: int, body: SplitListCreate, request: Request):
    current_user = getattr(request.state, "user", None) or {}
    txn = await _repo().get_transaction(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _check_txn_ownership(txn, current_user)
    try:
        return await _splits().set_splits(
            transaction_id, [s.model_dump() for s in body.splits]
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/{transaction_id}/splits", status_code=204)
async def delete_splits(transaction_id: int, request: Request):
    current_user = getattr(request.state, "user", None) or {}
    txn = await _repo().get_transaction(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _check_txn_ownership(txn, current_user)
    await _splits().delete_splits(transaction_id)
