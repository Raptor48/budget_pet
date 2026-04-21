"""Detect Plaid API errors that require the user to run Link update mode."""

from __future__ import annotations

import json
from typing import Any

try:
    from plaid.exceptions import ApiException
except ImportError:  # pragma: no cover
    ApiException = ()  # type: ignore[misc,assignment]

# https://plaid.com/docs/errors/item/
_REAUTH_ERROR_CODES = frozenset(
    {
        "ITEM_LOGIN_REQUIRED",
        "INSUFFICIENT_CREDENTIALS",
        "ITEM_LOCKED",
        "USER_SETUP_REQUIRED",
        "INVALID_ACCESS_TOKEN",
        "ITEM_NOT_FOUND",
    }
)


def _coerce_error_payload(body: Any) -> dict[str, Any]:
    if body is None:
        return {}
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    return {}


def plaid_error_requires_item_reauth(exc: BaseException) -> bool:
    """True when Plaid indicates this Item must be refreshed via Link (update mode)."""
    if ApiException and isinstance(exc, ApiException):
        data = _coerce_error_payload(getattr(exc, "body", None))
        code = (data.get("error_code") or "").upper()
        if code in _REAUTH_ERROR_CODES:
            return True

    text = str(exc)
    if "ITEM_LOGIN_REQUIRED" in text or "INSUFFICIENT_CREDENTIALS" in text:
        return True
    lower = text.lower()
    if "user login is required" in lower and "link" in lower:
        return True
    if "link's update mode" in lower or "link update mode" in lower:
        return True
    return False
