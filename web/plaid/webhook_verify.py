"""Verify Plaid-Verification JWT on incoming webhooks (optional in sandbox / tests).

Full verification per https://plaid.com/docs/api/webhooks/webhook-verification/:
  1. Verify JWT signature using Plaid's JWKS endpoint.
  2. Verify `iat` claim is no older than 5 minutes (replay attack prevention).
  3. Verify SHA-256 of the raw request body matches `request_body_sha256` claim.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)

# Plaid requires webhooks to be no older than 5 minutes.
_MAX_AGE_SECONDS = 300

try:
    import jwt
    from jwt import PyJWKClient
    _JWT_AVAILABLE = True
except ImportError:
    jwt = None  # type: ignore[assignment]
    PyJWKClient = None  # type: ignore[assignment,misc]
    _JWT_AVAILABLE = False


def verify_plaid_webhook(request: "Request", body: bytes) -> bool:
    if os.getenv("PLAID_SKIP_WEBHOOK_VERIFY", "").lower() in ("1", "true", "yes"):
        return True
    env = os.getenv("PLAID_ENV", "sandbox").lower()
    token = request.headers.get("Plaid-Verification") or request.headers.get("plaid-verification")
    if not token:
        # Sandbox webhooks fired via /sandbox/item/fire_webhook may not carry a JWT.
        return env == "sandbox"

    if not _JWT_AVAILABLE:
        logger.warning("PyJWT missing — rejecting webhook in non-sandbox")
        return env == "sandbox"

    host = "sandbox.plaid.com" if env == "sandbox" else "production.plaid.com"
    jwks_url = f"https://{host}/.well-known/jwks.json"
    try:
        jwks = PyJWKClient(jwks_url)
        signing_key = jwks.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
    except Exception as exc:
        logger.warning("Plaid webhook JWT verify failed: %s", exc)
        return False

    # 2. Replay attack prevention — reject webhooks older than 5 minutes.
    iat = payload.get("iat")
    if iat is None or (time.time() - float(iat)) > _MAX_AGE_SECONDS:
        logger.warning("Plaid webhook rejected: iat too old or missing (iat=%s)", iat)
        return False

    # 3. Body integrity — SHA-256 of raw body must match the claim.
    claimed_hash = payload.get("request_body_sha256")
    if not claimed_hash:
        logger.warning("Plaid webhook JWT missing request_body_sha256 claim")
        return False
    body_hash = hashlib.sha256(body).hexdigest()
    if not hmac.compare_digest(body_hash, claimed_hash):
        logger.warning("Plaid webhook body hash mismatch")
        return False

    return True
