"""Verify Plaid-Verification JWT on incoming webhooks (optional in sandbox / tests)."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)


def verify_plaid_webhook(request: "Request", body: bytes) -> bool:  # noqa: ARG001 — body reserved for signed payloads
    if os.getenv("PLAID_SKIP_WEBHOOK_VERIFY", "").lower() in ("1", "true", "yes"):
        return True
    env = os.getenv("PLAID_ENV", "sandbox").lower()
    token = request.headers.get("Plaid-Verification") or request.headers.get("plaid-verification")
    if not token:
        return env == "sandbox"
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError:
        logger.warning("PyJWT missing — rejecting webhook in non-sandbox")
        return env == "sandbox"

    host = "sandbox.plaid.com" if env == "sandbox" else "production.plaid.com"
    jwks_url = f"https://{host}/.well-known/jwks.json"
    try:
        jwks = PyJWKClient(jwks_url)
        signing_key = jwks.get_signing_key_from_jwt(token)
        jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
        return True
    except Exception as exc:
        logger.warning("Plaid webhook JWT verify failed: %s", exc)
        return False
