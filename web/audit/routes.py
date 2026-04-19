"""FastAPI routes for the audit log."""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from .models import AuditEntry, AuditListResponse
from .repo import get_audit_repo
from .service import record as audit_record

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _require_owner(request: Request) -> dict:
    user = getattr(request.state, "user", None) or {}
    if user.get("id") is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not user.get("is_owner"):
        raise HTTPException(status_code=403, detail="Owner role required")
    return user


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


@router.delete("")
async def clear_audit_log(
    request: Request,
    category: Optional[str] = Query(
        None,
        description=(
            "Optional namespace filter — e.g. 'plaid', 'auth', 'settings'. "
            "Deletes only rows whose event_type starts with 'category.'."
        ),
    ),
    before_id: Optional[int] = Query(
        None,
        ge=1,
        description=(
            "Optional cursor; only rows with ``id < before_id`` are deleted. "
            "Use this to wipe older pages while keeping the latest ones."
        ),
    ),
):
    """Owner-only. Delete audit rows matching the filter.

    After the delete we write one final ``audit.log_cleared`` row so
    there's always a breadcrumb pointing at who wiped the log, how many
    rows were removed, and which filter they used.
    """
    user = _require_owner(request)
    repo = get_audit_repo()
    prefix = f"{category}." if category else None
    deleted = await repo.delete(event_prefix=prefix, before_id=before_id)

    await audit_record(
        "audit.log_cleared",
        source="manual",
        request=request,
        metadata={
            "rows_deleted": deleted,
            "category": category,
            "before_id": before_id,
        },
    )
    return {"deleted": deleted, "cleared_by": user.get("username")}
