"""Orchestration for the merchant-logo enrichment loop.

One public entrypoint — :func:`enrich_merchants_via_brandfetch` —
called from the Plaid sync scheduler after a successful sync. It picks
up to ``limit`` merchant_names that need attention (per
:meth:`MerchantLogosRepository.names_to_enrich`), runs a single
Brandfetch search call each, and persists the outcome.

Why search-only (no Brand API call)? Because Brand Search's response
already carries an ``icon`` URL with a clientId baked in that the
browser can hotlink directly. The metered Brand API is reserved for
the institution-logo path where we need server-fetchable *bytes*. For
merchants we never need bytes — the frontend renders ``<img src=...>``
from the URL, no proxying.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .brandfetch import best_match, is_configured, search
from .repo import MerchantLogosRepository

logger = logging.getLogger(__name__)

# Throttle between successive search calls. Brandfetch's free Search
# tier rate-limits at the CloudFront edge with a generic "Slow down."
# 429 (no Retry-After header). Empirically a ~5 req/sec burst trips it
# and then CloudFront keeps the IP blocked for several minutes.
# 700ms ≈ 1.4 req/sec stays well clear; a 254-merchant backfill takes
# ~3 minutes, which is fine for a fire-and-forget background task that
# runs after the user-visible sync already completed.
_THROTTLE_SLEEP_SEC = 0.7

# Brandfetch's qualityScore floor below which we declare "low quality"
# and back off. Empirically (see scoping report) ≥0.5 catches all real
# brands (DoorDash 0.90, Affirm 0.96, Brooklyn Fare 0.51) while
# excluding generic-phrase autocompletes ("Pay Monthly" hits at 0.37).
_QUALITY_THRESHOLD = 0.5

# Per-sync batch cap. With ~5–10 new merchants per month after the
# initial backfill, this is generous enough to clear the queue in one
# run yet small enough to keep a single sync's enrichment phase under
# a few seconds even if every lookup goes the slow path.
_BATCH_LIMIT = 50


async def enrich_merchants_via_brandfetch(limit: int = _BATCH_LIMIT) -> dict:
    """Resolve up to ``limit`` merchant_names without logos.

    Idempotent, best-effort. Returns a count summary suitable for the
    audit log. Skips silently when Brandfetch isn't configured (no env
    vars) — the empty result then carries through as gradient avatars
    on the frontend, which is the same UX we have today.
    """
    summary = {"checked": 0, "resolved": 0, "no_hit": 0, "low_quality": 0}
    if not is_configured():
        return summary

    repo = MerchantLogosRepository()
    names = await repo.names_to_enrich(limit=limit)
    if not names:
        return summary

    for i, name in enumerate(names):
        summary["checked"] += 1
        # Inter-call throttle (skip on the first item). The retry-on-429
        # in search() backstops bursts that slip through, but the steady
        # pace here is what keeps us from tripping the limit at all.
        if i > 0:
            await asyncio.sleep(_THROTTLE_SLEEP_SEC)
        try:
            hits = await search(name)
            if not hits:
                await repo.mark_miss(name, "no_hit")
                summary["no_hit"] += 1
                continue
            # Pass `query=name` so the name-similarity gate kicks in.
            # Bank descriptors are often weird (timestamped, truncated,
            # abbreviated) so a quality-only filter happily admits a
            # high-completeness but unrelated brand. With the gate,
            # "2BP" no longer resolves to "2B Played".
            top = best_match(hits, min_quality=_QUALITY_THRESHOLD, query=name)
            if not top:
                await repo.mark_miss(name, "low_quality")
                summary["low_quality"] += 1
                continue
            icon = top.get("icon")
            if not icon:
                # Brandfetch returned a match that for some reason
                # lacks an icon URL. Treat the same as low_quality so
                # we back off rather than retry every sync.
                await repo.mark_miss(name, "low_quality")
                summary["low_quality"] += 1
                continue
            await repo.upsert_resolved(
                name,
                logo_url=icon,
                brand_domain=top.get("domain") or "",
                quality_score=float(top.get("qualityScore") or 0),
            )
            summary["resolved"] += 1
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.info("merchant enrich failed for %r: %s", name, exc)
            # Don't mark a miss here — a transport error is not a "this
            # brand doesn't exist" signal. Let the next sync retry.

    if summary["checked"]:
        logger.info("brandfetch merchant enrichment: %s", summary)
    return summary


# Module-level set of in-flight enrichment tasks. Without holding strong
# references, asyncio.create_task() can have its tasks garbage-collected
# mid-run on Python 3.11+. The set is cleared as tasks complete via the
# done-callback, so it never grows past whatever is actually running
# (almost always 0 or 1).
_in_flight: set[asyncio.Task] = set()


def schedule_merchant_enrichment(limit: int = _BATCH_LIMIT) -> Optional[asyncio.Task]:
    """Fire-and-forget kickoff for the merchant enrichment loop.

    Used by the Plaid sync scheduler so the user-visible sync time
    doesn't include the throttled Brandfetch search loop. Returns the
    task handle for tests; production callers ignore it.

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
