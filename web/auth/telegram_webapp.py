"""
Telegram WebApp (Mini App) initData validation.

When a user opens our Mini App from inside Telegram, the client passes a
signed ``initData`` query string identifying who they are. This module
verifies the HMAC signature against our bot token and returns the parsed
user dict, so we can mint a regular session for that account without a
password prompt.

Reference: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

Algorithm:
  1. Parse the query string into key/value pairs.
  2. Remove ``hash``; sort the remaining keys; join with newlines as
     ``key=value`` pairs to form ``data_check_string``.
  3. ``secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)``
  4. ``computed = HMAC_SHA256(key=secret_key, msg=data_check_string)``
  5. Compare ``computed.hexdigest()`` to ``hash`` in constant time.
  6. Reject if ``auth_date`` is older than ``max_age_seconds`` (replay
     protection).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)

# Default replay window. Telegram itself suggests "a few hours"; 24h covers
# users who keep the Mini App open across a workday without reopening.
DEFAULT_MAX_AGE_SECONDS = 24 * 3600


def verify_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> Optional[Dict[str, Any]]:
    """Validate ``init_data`` and return the parsed user dict.

    Returns the ``user`` payload from initData on success, or ``None`` on
    any failure (bad signature, missing fields, expired auth_date). All
    failures are logged at WARN level — never raise, so callers can treat
    a None return as "not a valid Telegram user, fall through to manual
    login".
    """
    if not init_data or not bot_token:
        return None

    # ``parse_qsl`` keeps duplicate keys in order; for initData each key
    # appears exactly once, so a dict roundtrip is safe.
    pairs = parse_qsl(init_data, keep_blank_values=True)
    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        logger.warning("telegram webapp initData missing hash")
        return None

    # Build the data-check string from remaining pairs sorted by key.
    data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data))

    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    computed = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        logger.warning("telegram webapp initData hash mismatch")
        return None

    # Replay protection — Telegram's auth_date is unix seconds.
    auth_date_raw = data.get("auth_date")
    if auth_date_raw is None:
        logger.warning("telegram webapp initData missing auth_date")
        return None
    try:
        auth_date = int(auth_date_raw)
    except ValueError:
        logger.warning("telegram webapp initData has malformed auth_date=%r", auth_date_raw)
        return None
    if (time.time() - auth_date) > max_age_seconds:
        logger.warning("telegram webapp initData expired (age=%ds)", int(time.time() - auth_date))
        return None

    user_raw = data.get("user")
    if not user_raw:
        logger.warning("telegram webapp initData missing user payload")
        return None
    try:
        user = json.loads(user_raw)
    except (ValueError, TypeError):
        logger.warning("telegram webapp initData has malformed user JSON")
        return None
    if not isinstance(user, dict) or "id" not in user:
        logger.warning("telegram webapp initData user dict missing id")
        return None
    return user
