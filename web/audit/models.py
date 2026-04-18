"""Pydantic models for the audit log module."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AuditEntry(BaseModel):
    id: int
    created_at: datetime
    actor_user_id: Optional[int] = None
    actor_username: Optional[str] = None
    event_type: str
    source: str
    target_kind: Optional[str] = None
    target_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
    request_ip: Optional[str] = None

    class Config:
        from_attributes = True


class AuditListResponse(BaseModel):
    entries: List[AuditEntry]
    next_before_id: Optional[int] = None
