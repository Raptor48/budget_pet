"""Audit-log recording helper.

Single entry point used across the codebase so call sites stay one-liners.
Guarantees it never raises — audit failures must not break product flows.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import Request

from .repo import get_audit_repo

logger = logging.getLogger(__name__)


def _client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    try:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ips = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
            if ips:
                return ips[-1]
        if request.client and request.client.host:
            return request.client.host
    except Exception:
        return None
    return None


def _actor_from_request(request: Optional[Request]) -> tuple[Optional[int], Optional[str]]:
    if request is None:
        return None, None
    user = getattr(request.state, "user", None)
    if not user:
        return None, None
    uid = user.get("id")
    try:
        uid_int = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        uid_int = None
    return uid_int, user.get("username")


async def record(
    event_type: str,
    *,
    source: str = "manual",
    request: Optional[Request] = None,
    actor: Optional[Dict[str, Any]] = None,
    target_kind: Optional[str] = None,
    target_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Record one audit entry. Never raises.

    Returns the new row id, or None if the write failed.
    """
    try:
        actor_uid: Optional[int] = None
        actor_username: Optional[str] = None
        if actor:
            raw_uid = actor.get("id")
            try:
                actor_uid = int(raw_uid) if raw_uid is not None else None
            except (TypeError, ValueError):
                actor_uid = None
            actor_username = actor.get("username")
        else:
            actor_uid, actor_username = _actor_from_request(request)

        ip = _client_ip(request)

        repo = get_audit_repo()
        return await repo.insert(
            event_type=event_type,
            source=source,
            actor_user_id=actor_uid,
            actor_username=actor_username,
            target_kind=target_kind,
            target_id=str(target_id) if target_id is not None else None,
            metadata=metadata or {},
            request_ip=ip,
        )
    except Exception as exc:
        logger.warning(
            "audit.record failed (event=%s, source=%s): %s",
            event_type,
            source,
            exc,
            exc_info=False,
        )
        return None
