"""Brandfetch HTTP client — minimal, best-effort, async.

Two free-tier endpoints we lean on:

* **Brand Search** (``/v2/search/{query}``) — name → ranked candidates
  including an embeddable ``icon`` URL with our clientId baked in. Free
  and unlimited; this is the workhorse for the merchant pipeline.
* **Brand API** (``/v2/brands/{domain}``) — domain → full asset catalog
  with signed CDN URLs that work server-side (per-request credentials).
  Bearer auth, 100 lookups/month free. Used when we need *bytes* (not
  just an embed URL) — e.g. for the institution_logo TEXT column that
  Plaid populates as raw base64 PNG.

Design notes:

* Every public function is *best-effort*: returns ``None`` / ``[]`` on
  any failure (network, auth, rate limit, no hit). A flaky third-party
  must never propagate an exception into a Plaid sync or app startup.
* Configuration is read from env on each call rather than cached at
  import time, so flipping the env var doesn't require a restart for
  the next call to pick it up. Cost is two ``os.getenv()`` per request
  — negligible vs the network round-trip.
* httpx (not aiohttp) because Brandfetch's CloudFront WAF returns 403
  on aiohttp's default TLS fingerprint — verified empirically. httpx
  is already a transitive project dep, so this adds no new install.
"""

from __future__ import annotations

import base64
import logging
import os
from io import BytesIO
from typing import Optional
from urllib.parse import quote

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

_API_BASE = "https://api.brandfetch.io/v2"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# A real-looking UA + a project identifier — Brandfetch's WAF tolerates
# httpx defaults, but the explicit UA is grep-friendly for ops who want
# to track our calls in their audit log.
_USER_AGENT = (
    "budget_pet/1.0 (+https://github.com/Raptor48/budget_pet) httpx"
)
_HEADERS = {"User-Agent": _USER_AGENT}

# Maximum asset payload we'll base64 into a TEXT column. 1MB is well
# above any real Brandfetch icon (top end ~30KB for a 800x800 PNG) but
# below the point at which storing it in Postgres becomes silly.
_ASSET_MAX_BYTES = 1_000_000


def _api_key() -> Optional[str]:
    val = os.getenv("BRANDFETCH_API_KEY", "").strip()
    return val or None


def _client_id() -> Optional[str]:
    val = os.getenv("BRANDFETCH_CLIENT_ID", "").strip()
    return val or None


def is_configured() -> bool:
    """True when the Brand Search path is usable (clientId set).

    Brand Search needs only the clientId — the Bearer API key is for the
    metered Brand API endpoint and is checked separately via
    :func:`has_brand_api`.
    """
    return _client_id() is not None


def has_brand_api() -> bool:
    """True when the Brand API (Bearer-auth, metered) is available."""
    return _api_key() is not None


async def search(query: str) -> list[dict]:
    """Brand Search → ranked list of matches.

    Returns the parsed JSON list (possibly empty). Returns ``[]`` on any
    transport-level failure so callers don't need try/except for the
    common case.

    Each hit has keys we care about:

    * ``name``, ``domain`` — display + canonical lookup id
    * ``qualityScore`` (0–1) — how complete Brandfetch's record is.
      *This is not search relevance.* For our merchant pipeline we
      filter on this to discard junk autocompletes; for known good
      brands (Affirm, DoorDash) it's ≥0.9.
    * ``brandId`` — opaque id, useful for constructing logo URLs
    * ``icon`` — ready-to-embed CDN URL for a small representation
    * ``claimed``, ``verified`` — provenance signals
    """
    cid = _client_id()
    if not cid:
        return []
    q = query.strip()
    if not q:
        return []
    url = f"{_API_BASE}/search/{quote(q)}?c={cid}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.info("brandfetch search %r → HTTP %s", q, resp.status_code)
                return []
            data = resp.json()
            if not isinstance(data, list):
                return []
            return data
    except Exception as exc:  # noqa: BLE001 — best-effort lookup, swallow
        logger.info("brandfetch search %r failed: %s", q, exc)
        return []


async def get_brand(domain: str) -> Optional[dict]:
    """Brand API → full brand record for ``domain``.

    Requires ``BRANDFETCH_API_KEY``. The returned ``logos[*].formats[*].src``
    URLs carry per-request credentials, so they can be fetched server-side
    (the public domain-shortcut URLs cannot).
    """
    key = _api_key()
    if not key:
        return None
    d = domain.strip()
    if not d:
        return None
    url = f"{_API_BASE}/brands/{d}"
    headers = {**_HEADERS, "Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.info("brandfetch brand %s → HTTP %s", d, resp.status_code)
                return None
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.info("brandfetch brand %s failed: %s", d, exc)
        return None


def best_match(results: list[dict], min_quality: float = 0.5) -> Optional[dict]:
    """Pick the highest-``qualityScore`` hit that clears ``min_quality``.

    Search results are pre-sorted by ``_score`` (relevance for the query)
    but for our use-case ``qualityScore`` (record completeness) is what
    keeps junk autocompletes out. We pick the most-complete brand among
    those that clear the threshold, falling back to ``None`` when nothing
    qualifies.
    """
    if not results:
        return None
    qualified = [r for r in results if (r.get("qualityScore") or 0) >= min_quality]
    if not qualified:
        return None
    return max(qualified, key=lambda r: r.get("qualityScore") or 0)


def pick_icon_url(brand: dict) -> Optional[str]:
    """Pick the best server-fetchable square asset from a Brand API response.

    Two passes:

    1. PNG across ``icon`` → ``symbol`` → ``logo`` types.
    2. JPEG fallback in the same order.

    Format takes priority over type because the institution_logo column
    is rendered as ``data:image/png;...`` on the frontend — falling back
    to JPEG within a type before checking PNG of the next type would
    land us a JPEG when a perfectly good PNG (e.g. Chase's symbol PNG)
    was available. ``fetch_asset_as_png_base64`` normalizes the bytes
    to PNG regardless, but starting from PNG avoids a recompression.

    SVG is skipped — there's no clean path from SVG to base64 PNG
    without a rasterizer (cairosvg, resvg), and Brandfetch always ships
    at least one raster format alongside SVG for claimed brands.
    """
    logos = brand.get("logos") or []
    for fmt_pref in ("png", "jpeg"):
        for type_pref in ("icon", "symbol", "logo"):
            for entry in logos:
                if entry.get("type") != type_pref:
                    continue
                for fmt in entry.get("formats") or []:
                    if fmt.get("format") == fmt_pref and fmt.get("src"):
                        return fmt["src"]
    return None


async def fetch_asset_as_png_base64(url: str) -> Optional[str]:
    """GET an asset URL → base64 PNG string (no ``data:`` prefix).

    The output is always PNG bytes, regardless of what Brandfetch served
    (JPEG, WebP, ...). This matches the institution_logo render path on
    the frontend, which hardcodes ``data:image/png;base64,...``.

    Conversion goes through Pillow. SVG inputs are rejected — see
    :func:`pick_icon_url` for why we only request raster URLs upstream.

    Caps the source payload at ~1MB to avoid runaway TEXT bloat —
    Brandfetch icons are typically 10–30 KB, so a 1MB response is a
    strong signal that we asked for the wrong asset (e.g. a banner).
    """
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.info(
                    "brandfetch asset fetch → HTTP %s for %s...",
                    resp.status_code,
                    url[:80],
                )
                return None
            content = resp.content
            if len(content) > _ASSET_MAX_BYTES:
                logger.info(
                    "brandfetch asset >1MB skipped (%d bytes) for %s...",
                    len(content),
                    url[:80],
                )
                return None
            try:
                img = Image.open(BytesIO(content))
                buf = BytesIO()
                # Convert to RGBA → preserves transparency for symbol-type
                # icons that ship as PNGA. JPEG inputs (no alpha) just
                # carry a fully-opaque alpha channel through, which the
                # final PNG can compress out anyway.
                img.convert("RGBA").save(buf, format="PNG", optimize=True)
                png_bytes = buf.getvalue()
            except Exception as exc:  # noqa: BLE001
                logger.info("PIL conversion failed for %s...: %s", url[:80], exc)
                return None
            return base64.b64encode(png_bytes).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        logger.info("brandfetch asset fetch failed: %s", exc)
        return None
