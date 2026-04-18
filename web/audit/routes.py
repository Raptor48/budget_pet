"""FastAPI routes for the audit log."""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from .models import AuditEntry, AuditListResponse
from .repo import get_audit_repo

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=AuditListResponse)
async def list_audit(
    limit: int = Query(50, ge=1, le=200),
    before_id: Optional[int] = Query(None, ge=1),
    event_type: Optional[str] = Query(None, description="Exact event_type match"),
    category: Optional[str] = Query(
        None,
        description="Event namespace filter — e.g. 'plaid', 'auth', 'settings'. Matches 'category.*'.",
    ),
):
    """Return the most recent audit entries in reverse chronological order.

    Cursor pagination uses `before_id`: pass the last row id seen to fetch
    the next page.
    """
    prefix = f"{category}." if category else None
    repo = get_audit_repo()
    rows = await repo.list(
        limit=limit,
        before_id=before_id,
        event_type=event_type,
        event_prefix=prefix,
    )
    entries: List[AuditEntry] = [AuditEntry(**r) for r in rows]
    next_before = entries[-1].id if len(entries) == limit else None
    return AuditListResponse(entries=entries, next_before_id=next_before)


@router.get("/event-types", response_model=List[str])
async def list_event_types():
    repo = get_audit_repo()
    try:
        return await repo.event_types()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
