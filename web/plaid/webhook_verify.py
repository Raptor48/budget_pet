"""Verify Plaid-Verification JWT on incoming webhooks (optional in sandbox / tests).

Per https://plaid.com/docs/api/webhooks/webhook-verification/:
  1. Read JWT header (``kid``, ``alg``); ``alg`` must be ES256.
  2. Fetch the JWK via Plaid ``/webhook_verification_key/get`` (not a static JWKS URL).
  3. Verify JWT signature, ``iat`` within 5 minutes, and ``request_body_sha256`` vs body.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)

# Plaid requires webhooks to be no older than 5 minutes.
_MAX_AGE_SECONDS = 300

_JWK_CACHE: Dict[str, Dict[str, Any]] = {}
_JWK_CACHE_LOCK = threading.Lock()

# Standard JWK members for PyJWT / cryptography (Plaid adds created_at, etc.).
_JWK_WHITELIST = frozenset({"kty", "crv", "x", "y", "kid", "use", "alg"})

try:
    import jwt
    from jwt import PyJWK

    _JWT_AVAILABLE = True
except ImportError:
    jwt = None  # type: ignore[assignment]
    PyJWK = None  # type: ignore[assignment,misc]
    _JWT_AVAILABLE = False


def clear_plaid_webhook_jwk_cache() -> None:
    """Clear cached webhook verification keys (tests only)."""
    with _JWK_CACHE_LOCK:
        _JWK_CACHE.clear()


def _normalize_plaid_jwk(key: Dict[str, Any]) -> Dict[str, Any]:
    return {k: key[k] for k in _JWK_WHITELIST if k in key and key[k] is not None}


def _fetch_plaid_verification_jwk(kid: str) -> Optional[Dict[str, Any]]:
    """Call Plaid /webhook_verification_key/get for this key id."""
    from plaid.model.webhook_verification_key_get_request import WebhookVerificationKeyGetRequest

    from web.plaid.client import get_plaid_client

    try:
        client = get_plaid_client()
        resp = client.webhook_verification_key_get(WebhookVerificationKeyGetRequest(key_id=kid))
        key_obj = resp.get("key")
        raw = key_obj.to_dict() if hasattr(key_obj, "to_dict") else dict(key_obj)
        return _normalize_plaid_jwk(raw)
    except Exception as exc:
        logger.warning("Plaid webhook_verification_key/get failed for kid=%s: %s", kid, exc)
        return None


def _get_cached_plaid_jwk(kid: str) -> Optional[Dict[str, Any]]:
    with _JWK_CACHE_LOCK:
        cached = _JWK_CACHE.get(kid)
    if cached is not None:
        return cached
    jwk = _fetch_plaid_verification_jwk(kid)
    if jwk is None:
        return None
    with _JWK_CACHE_LOCK:
        _JWK_CACHE[kid] = jwk
    return jwk


def _load_signing_key(token: str) -> Any:
    """Return a cryptography public key for jwt.decode(..., algorithms=[\"ES256\"])."""
    if not _JWT_AVAILABLE or jwt is None or PyJWK is None:
        raise RuntimeError("PyJWT not available")
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "ES256":
        raise ValueError(f"unexpected JWT alg: {header.get('alg')!r}")
    kid = header.get("kid")
    if not kid:
        raise ValueError("JWT header missing kid")
    jwk_dict = _get_cached_plaid_jwk(str(kid))
    if not jwk_dict:
        raise ValueError("could not load Plaid webhook verification JWK")
    return PyJWK.from_dict(jwk_dict).key


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

    try:
        signing_key = _load_signing_key(token)
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
    except Exception as exc:
        logger.warning("Plaid webhook JWT verify failed: %s", exc)
        return False

    # Replay attack prevention — reject webhooks older than 5 minutes.
    iat = payload.get("iat")
    if iat is None or (time.time() - float(iat)) > _MAX_AGE_SECONDS:
        logger.warning("Plaid webhook rejected: iat too old or missing (iat=%s)", iat)
        return False

    claimed_hash = payload.get("request_body_sha256")
    if not claimed_hash:
        logger.warning("Plaid webhook JWT missing request_body_sha256 claim")
        return False
    body_hash = hashlib.sha256(body).hexdigest()
    if not hmac.compare_digest(body_hash, claimed_hash):
        logger.warning("Plaid webhook body hash mismatch")
        return False

    return True
