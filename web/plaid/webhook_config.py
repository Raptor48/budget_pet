"""
Webhook toggle helpers.

Reconciling webhooks means pushing the current "webhooks enabled?" decision from
``app_settings`` to Plaid for every linked item, by calling ``/item/webhook/update``.

Why this matters: flipping the toggle in our DB does nothing by itself — Plaid
keeps sending webhooks to the URL it already has on file. To actually stop the
pushes (and the $0.10 Balance calls they trigger), we must clear the webhook
URL on every existing Item at Plaid. Re-enabling does the reverse.

Callers:
* ``PATCH /api/settings/app`` — when ``webhooks_enabled`` changes.
* one-shot ops command / tests.

Never raises: individual item failures are logged and surfaced in the returned
summary so the UI can warn the user without breaking the rest of the request.
"""
import logging
import os
from typing import Dict, List

from .client import update_item_webhook
from .repo import get_plaid_repo

logger = logging.getLogger(__name__)


def configured_webhook_url() -> str:
    """Return the webhook URL from the environment (empty string if unset)."""
    return (os.getenv("PLAID_WEBHOOK_URL") or "").strip()


async def reconcile_item_webhooks(enabled: bool) -> Dict[str, object]:
    """Push ``enabled`` to Plaid for every linked item.

    When ``enabled`` is True the configured ``PLAID_WEBHOOK_URL`` is registered.
    When ``enabled`` is False an empty string is sent, which Plaid interprets
    as "stop sending webhooks for this Item".

    If ``enabled`` is True but ``PLAID_WEBHOOK_URL`` is not configured, this is
    a no-op that returns ``updated=0`` with an explanatory error entry — we
    never send an empty webhook when the caller asked for webhooks on.
    """
    webhook_url = configured_webhook_url()
    target = webhook_url if enabled else ""

    if enabled and not webhook_url:
        logger.warning(
            "reconcile_item_webhooks(enabled=True) called but PLAID_WEBHOOK_URL is unset"
        )
        return {
            "updated": 0,
            "failed": 0,
            "total": 0,
            "errors": [
                "PLAID_WEBHOOK_URL is not configured; cannot register webhooks."
            ],
        }

    repo = get_plaid_repo()
    try:
        items = await repo.get_items()
    except Exception as exc:
        logger.error("Failed to load plaid_items during webhook reconcile: %s", exc)
        return {
            "updated": 0,
            "failed": 0,
            "total": 0,
            "errors": [f"Failed to load items: {exc}"],
        }

    updated = 0
    failed = 0
    errors: List[str] = []
    for item in items:
        access_token = item.get("access_token")
        item_id = item.get("item_id")
        if not access_token:
            continue
        try:
            ok = update_item_webhook(access_token, target)
        except Exception as exc:  # defensive — client already catches, but be safe
            logger.warning("update_item_webhook raised for %s: %s", item_id, exc)
            ok = False
        if ok:
            updated += 1
        else:
            failed += 1
            errors.append(f"item {item_id}: Plaid rejected webhook update")

    return {
        "updated": updated,
        "failed": failed,
        "total": updated + failed,
        "errors": errors,
    }
