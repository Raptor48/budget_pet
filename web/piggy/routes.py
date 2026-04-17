"""
Piggy Banks — savings goals. Backed by finance_piggy_banks table (legacy schema, kept in V2).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web.db import get_pool

router = APIRouter(prefix="/api/piggy", tags=["piggy"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PiggyBankOut(BaseModel):
    id: int
    name: str
    target_amount_cents: int
    current_amount_cents: int
    color: str
    icon: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[str] = None
    is_active: bool


class PiggyBankCreate(BaseModel):
    name: str
    target_amount_cents: int
    current_amount_cents: int = 0
    color: str = "#3b82f6"
    icon: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[str] = None
    is_active: bool = True


class PiggyBankUpdate(BaseModel):
    name: Optional[str] = None
    target_amount_cents: Optional[int] = None
    current_amount_cents: Optional[int] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[str] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    if d.get("deadline"):
        d["deadline"] = str(d["deadline"])
    return d


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=List[PiggyBankOut])
async def list_piggy_banks(active_only: bool = False):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if active_only:
            rows = await conn.fetch(
                "SELECT * FROM finance_piggy_banks WHERE is_active = TRUE ORDER BY created_at DESC"
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM finance_piggy_banks ORDER BY created_at DESC"
            )
    return [_row_to_dict(r) for r in rows]


@router.post("", response_model=PiggyBankOut, status_code=201)
async def create_piggy_bank(data: PiggyBankCreate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO finance_piggy_banks
                (name, target_amount_cents, current_amount_cents, color, icon, description, deadline, is_active)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            RETURNING *
            """,
            data.name,
            data.target_amount_cents,
            data.current_amount_cents,
            data.color,
            data.icon,
            data.description,
            data.deadline,
            data.is_active,
        )
    return _row_to_dict(row)


@router.get("/{piggy_id}", response_model=PiggyBankOut)
async def get_piggy_bank(piggy_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM finance_piggy_banks WHERE id = $1", piggy_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Piggy bank not found")
    return _row_to_dict(row)


@router.patch("/{piggy_id}", response_model=PiggyBankOut)
async def update_piggy_bank(piggy_id: int, data: PiggyBankUpdate):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        return await get_piggy_bank(piggy_id)
    set_clause = ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(updates.keys()))
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE finance_piggy_banks SET {set_clause}, updated_at = NOW() WHERE id = $1 RETURNING *",
            piggy_id,
            *updates.values(),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Piggy bank not found")
    return _row_to_dict(row)


@router.post("/{piggy_id}/add", response_model=PiggyBankOut)
async def add_to_piggy_bank(piggy_id: int, amount_cents: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE finance_piggy_banks
            SET current_amount_cents = current_amount_cents + $2,
                updated_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            piggy_id,
            amount_cents,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Piggy bank not found")
    return _row_to_dict(row)


@router.delete("/{piggy_id}", status_code=204)
async def delete_piggy_bank(piggy_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM finance_piggy_banks WHERE id = $1", piggy_id
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Piggy bank not found")
