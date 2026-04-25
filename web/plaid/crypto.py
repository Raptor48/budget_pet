"""Fernet encryption for Plaid access tokens at rest.

Plaid access_tokens authorize unrestricted transaction reads against the
user's bank accounts, so storing them as plain TEXT in the DB is a real
risk: anyone with read access to a backup, dump, or compromised replica
walks away with bank-grade credentials.

This module wraps the symmetric Fernet primitive from ``cryptography``.
The key lives in the ``PLAID_ENCRYPTION_KEY`` env var (URL-safe base64,
44 chars). Generate one with::

    python3 -c "from cryptography.fernet import Fernet; \\
        print(Fernet.generate_key().decode())"

Operational rules:

- Once you set ``PLAID_ENCRYPTION_KEY`` and tokens get encrypted with
  it, **do not change the key**. Losing or rotating the key without a
  prior decrypt-and-re-encrypt pass makes every stored Plaid item
  unreachable — every bank connection has to be re-linked from the UI.
- Keep a backup of the key alongside your other production secrets
  (password manager, secrets vault). It is *not* recoverable from
  Railway alone.
- The repository is intentionally tolerant of missing keys: if
  ``PLAID_ENCRYPTION_KEY`` is unset, callers fall back to the plain
  ``access_token`` column. This keeps deploys green during the rollout
  window between code merge and env-var configuration.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_ENV_KEY = "PLAID_ENCRYPTION_KEY"
_fernet_singleton: Optional[Fernet] = None
_warned_missing_key = False


def _read_key_from_env() -> Optional[str]:
    raw = os.getenv(_ENV_KEY)
    if not raw:
        return None
    raw = raw.strip()
    return raw or None


def encryption_available() -> bool:
    """True when ``PLAID_ENCRYPTION_KEY`` is set. Cheap; safe to call hot."""
    return _read_key_from_env() is not None


def _get_fernet() -> Fernet:
    """Build/cache the Fernet instance. Raises if the env var is missing."""
    global _fernet_singleton
    if _fernet_singleton is not None:
        return _fernet_singleton
    raw = _read_key_from_env()
    if raw is None:
        raise RuntimeError(
            f"{_ENV_KEY} is not set. Generate one with "
            "`python3 -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and add it to Railway."
        )
    _fernet_singleton = Fernet(raw.encode())
    return _fernet_singleton


def encrypt(plain: str) -> bytes:
    """Encrypt a Plaid access token. Returns bytes safe for ``BYTEA``."""
    return _get_fernet().encrypt(plain.encode("utf-8"))


def decrypt(blob: bytes | bytearray | memoryview | str) -> str:
    """Decrypt a stored Plaid access token.

    Accepts bytes-like values (asyncpg returns ``memoryview`` for BYTEA)
    and the tolerant ``str`` form just in case a future caller stores the
    base64 already-stringified.

    Raises :class:`cryptography.fernet.InvalidToken` if the key has
    rotated or the blob is corrupted — bubble it up so the sync layer
    surfaces a real error instead of silently failing closed.
    """
    if isinstance(blob, memoryview):
        blob = bytes(blob)
    elif isinstance(blob, bytearray):
        blob = bytes(blob)
    elif isinstance(blob, str):
        blob = blob.encode("utf-8")
    return _get_fernet().decrypt(blob).decode("utf-8")


def warn_if_missing_once() -> None:
    """Log one CRITICAL line per process when the key is unset.

    Repo callers invoke this on the first DB read so operators see a
    loud, actionable message in Railway logs without spamming the
    log stream.
    """
    global _warned_missing_key
    if _warned_missing_key or encryption_available():
        return
    _warned_missing_key = True
    logger.critical(
        "%s is not set: Plaid access_tokens are stored as plain TEXT. "
        "Generate a key (Fernet.generate_key) and set it in Railway "
        "to encrypt-at-rest. See web/plaid/crypto.py docstring.",
        _ENV_KEY,
    )


__all__ = [
    "InvalidToken",
    "decrypt",
    "encrypt",
    "encryption_available",
    "warn_if_missing_once",
]
