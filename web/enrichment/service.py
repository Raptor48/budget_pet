"""Orchestration for the merchant-logo enrichment loop.

One public entrypoint — :func:`enrich_merchants_via_brandfetch` —
called from the Plaid sync scheduler after a successful sync. It picks
up to ``limit`` enrichment keys (per
:meth:`MerchantLogosRepository.names_to_enrich`) and resolves each
through a two-tier pipeline:

1. **Tier 1 — curated map.** :func:`known_services.lookup_known_service`
   returns a canonical domain for ~30 top-volume services where
   Brandfetch's search would mis-rank or miss entirely (Zelle, Chase
   Bank, Wells Fargo, ...). When a key matches, we skip search and
   hit Brand API directly with the curated domain.
2. **Tier 2 — Brandfetch search.** Free, ranked, similarity-gated.
   Used for the long tail.

Bank-noise keys ("Payment from Maria", "Wire Fee", account-mask
references) are short-circuited via :func:`known_services.is_bank_noise`
before either tier runs — those should never get a logo.

Why Brand API (not just search.icon) for the curated tier? Because
Brand API returns a richer logo catalogue keyed by the canonical
brand record (multiple resolutions, theme variants, claimed-by-brand
flag). For curated entries we know the domain is correct, so spending
1 Brand API call (out of 100/mo free) to get the best asset URL is
worth it. Tier-2 stays on search.icon because we don't know which of
the search hits is right with the same confidence.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .brandfetch import (
    best_match,
    get_brand,
    has_brand_api,
    is_configured,
    pick_icon_url,
    search,
)
from .known_services import is_bank_noise, lookup_known_service
from .repo import MerchantLogosRepository

logger = logging.getLogger(__name__)

# Throttle between successive Brandfetch calls. The free Search tier
# rate-limits at the CloudFront edge with a generic "Slow down." 429
# (no Retry-After header). Empirically a ~5 req/sec burst trips it and
# CloudFront keeps the IP blocked for several minutes. 700ms ≈ 1.4
# req/sec stays well clear; a ~1000-key backfill takes a few minutes,
# which is fine for a fire-and-forget background task that runs after
# the user-visible sync already completed. Applied to both tiers
# (curated path uses Brand API which is on its own quota but we keep
# one steady pace for cache-coherent debugging).
_THROTTLE_SLEEP_SEC = 0.7

# Brandfetch's qualityScore floor below which we declare "low quality"
# and back off. Empirically (see scoping report) ≥0.5 catches all real
# brands (DoorDash 0.90, Affirm 0.96, Brooklyn Fare 0.51) while
# excluding generic-phrase autocompletes ("Pay Monthly" hits at 0.37).
_QUALITY_THRESHOLD = 0.5

# Per-sync batch cap. After the initial backfill we expect 0–10 new
# keys per sync; this ceiling keeps each enrichment pass bounded even
# if the backfill is mid-flight from a previous Plaid item.
_BATCH_LIMIT = 50


async def enrich_merchants_via_brandfetch(limit: int = _BATCH_LIMIT) -> dict:
    """Resolve up to ``limit`` enrichment keys without logos.

    Idempotent, best-effort. Returns a count summary suitable for the
    audit log. Skips silently when Brandfetch isn't configured (no env
    vars) — the empty result then carries through as gradient avatars
    on the frontend, which is the same UX we have today.
    """
    summary = {
        "checked": 0,
        "resolved_curated": 0,
        "resolved_search": 0,
        "no_hit": 0,
        "low_quality": 0,
        "noise_skipped": 0,
    }
    if not is_configured():
        return summary

    repo = MerchantLogosRepository()
    keys = await repo.names_to_enrich(limit=limit)
    if not keys:
        return summary

    for i, key in enumerate(keys):
        summary["checked"] += 1
        # Throttle between API calls. Skip on the first iteration so a
        # single-key trigger doesn't tack on a wasted 700ms.
        if i > 0:
            await asyncio.sleep(_THROTTLE_SLEEP_SEC)

        # Bank-noise short-circuit — "Payment from Maria", "Wire Fee",
        # etc. should never be searched. Mark as no_hit so backoff
        # applies and we don't re-evaluate them every sync. They'll
        # never be re-evaluated regardless because `names_to_enrich`
        # picks the same noise strings each time, but the cache row is
        # what stops the Brandfetch call from happening.
        if is_bank_noise(key):
            await repo.mark_miss(key, "no_hit")
            summary["noise_skipped"] += 1
            continue

        try:
            # Tier 1: curated map for top-volume services where
            # Brandfetch search is wrong or unranked.
            curated_domain = lookup_known_service(key)
            if curated_domain and has_brand_api():
                resolved = await _resolve_via_curated_domain(
                    repo, key, curated_domain
                )
                if resolved:
                    summary["resolved_curated"] += 1
                    continue
                # Fall through to search if curated path failed for
                # some reason (Brand API down, asset missing, etc.).

            # Tier 2: Brandfetch search with similarity gate.
            resolved = await _resolve_via_search(repo, key, summary)
            # _resolve_via_search bumps the right summary key itself.
            _ = resolved  # explicitly unused — counters already updated
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.info("merchant enrich failed for %r: %s", key, exc)
            # Don't mark a miss here — a transport error is not a "this
            # brand doesn't exist" signal. Let the next sync retry.

    if summary["checked"]:
        logger.info("brandfetch merchant enrichment: %s", summary)
    return summary


async def _resolve_via_curated_domain(
    repo: MerchantLogosRepository,
    key: str,
    domain: str,
) -> bool:
    """Tier-1 helper: skip search, fetch the canonical brand record by
    domain and pick the best icon URL. Returns True when resolved.
    """
    brand = await get_brand(domain)
    if not brand:
        return False
    icon = pick_icon_url(brand)
    if not icon:
        return False
    # qualityScore is search-tier metadata; for curated entries we have
    # human-verified confidence so we record a sentinel 1.0 to make
    # the audit log obvious ("this came from the static map").
    await repo.upsert_resolved(
        key,
        logo_url=icon,
        brand_domain=domain,
        quality_score=1.0,
        status="resolved",
    )
    logger.info("enrichment: curated %r → %s", key, domain)
    return True


async def _resolve_via_search(
    repo: MerchantLogosRepository,
    key: str,
    summary: dict,
) -> bool:
    """Tier-2 helper: Brandfetch search + best_match + persist. Updates
    ``summary`` in place. Returns True on a successful save.
    """
    hits = await search(key)
    if not hits:
        await repo.mark_miss(key, "no_hit")
        summary["no_hit"] += 1
        return False
    # Pass `query=key` so the name-similarity gate kicks in. Bank
    # descriptors are often weird (truncated, abbreviated), so a
    # quality-only filter happily admits a high-completeness but
    # unrelated brand. With the gate, "2BP" no longer resolves to
    # "2B Played".
    top = best_match(hits, min_quality=_QUALITY_THRESHOLD, query=key)
    if not top:
        await repo.mark_miss(key, "low_quality")
        summary["low_quality"] += 1
        return False
    icon = top.get("icon")
    if not icon:
        await repo.mark_miss(key, "low_quality")
        summary["low_quality"] += 1
        return False
    await repo.upsert_resolved(
        key,
        logo_url=icon,
        brand_domain=top.get("domain") or "",
        quality_score=float(top.get("qualityScore") or 0),
    )
    summary["resolved_search"] += 1
    return True


# Module-level set of in-flight enrichment tasks. Without holding strong
# references, asyncio.create_task() can have its tasks garbage-collected
# mid-run on Python 3.11+. The set is cleared as tasks complete via the
# done-callback, so it never grows past whatever is actually running
# (almost always 0 or 1).
_in_flight: set[asyncio.Task] = set()


def schedule_merchant_enrichment(limit: int = _BATCH_LIMIT) -> Optional[asyncio.Task]:
    """Fire-and-forget kickoff for the merchant enrichment loop.

    Used by the Plaid sync scheduler so the user-visible sync time
    doesn't include the throttled Brandfetch loop. Returns the task
    handle for tests; production callers ignore it.

    If a previous enrichment is still running (e.g. a webhook-triggered
    sync fires while the scheduled sync is mid-enrichment), this is a
    no-op — duplicate runs only burn the rate budget on identical
    work, and the next sync will pick up anything still pending.
    """
    if not is_configured():
        return None
    if _in_flight:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — caller is sync-only or in shutdown. Skip
        # rather than try to create a new loop and surprise the caller
        # with thread semantics.
        return None
    task = loop.create_task(enrich_merchants_via_brandfetch(limit=limit))
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)
    return task
