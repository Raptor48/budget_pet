"""Logo candidate resolver for the user-curated merchant logos flow.

Given a domain typed in by the user, fan out to every logo source we
know about and return a list of ready-to-embed URLs the UI can render
side-by-side as a picker. The user picks one and we save the URL to
``merchant_logos`` with ``status='user_curated'``.

Sources (in the order they appear in the candidate list):

* **Brandfetch Brand API** — when our API key is configured and the
  domain happens to be in Brandfetch's catalogue, this is the highest
  quality option (themed PNG/SVG at multiple resolutions, often a
  brand-claimed asset). Returns up to 3 candidates: icon, symbol, logo.
* **faviconextractor** — universal fallback. Single endpoint
  ``https://www.faviconextractor.com/favicon/{domain}`` returns the
  site's actual favicon. Free, no key, no quality bar but always
  delivers if the domain exists. We request the default + ``?larger=true``
  variant for two effective sizes.
* **Google s2/favicons** — last-resort fallback that always returns
  *something* (often a 32x32 even for obscure domains). Three size
  variants: 64, 128, 256.

Each call is best-effort; a source that 404s or times out drops out
of the list without failing the whole request. The UI handles an
empty list gracefully (gradient avatar stays).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
from pydantic import BaseModel

from .brandfetch import (
    _HEADERS,
    _TIMEOUT,
    get_brand,
    has_brand_api,
)

logger = logging.getLogger(__name__)


# Pydantic model lives here so the routes layer can import it directly
# without round-tripping through dict shapes.
class LogoCandidate(BaseModel):
    url: str
    source: str  # 'brandfetch' | 'faviconextractor' | 'google'
    label: str   # human label rendered under the thumbnail, e.g. "Brandfetch · icon"


_DOMAIN_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?"
    r"([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+)"
    r"(?:/.*)?$",
    re.IGNORECASE,
)


def normalize_domain(raw: str) -> Optional[str]:
    """Strip scheme, ``www.``, path, and trailing junk to leave just the
    apex-or-subdomain part. Returns None when the input doesn't look
    like a domain at all.

    Examples::

        "https://www.brooklynfare.com/foo"  -> "brooklynfare.com"
        "BrooklynFare.com"                  -> "brooklynfare.com"
        "rover"                             -> None  (no TLD)
        ""                                  -> None
    """
    if not raw:
        return None
    s = raw.strip().lower()
    m = _DOMAIN_RE.match(s)
    if not m:
        return None
    return m.group(1)


async def _brandfetch_candidates(domain: str) -> list[LogoCandidate]:
    """Pull at most three visually distinct asset URLs out of a Brand
    API response — one ``icon``, one ``symbol``, one ``logo`` — so the
    picker shows real variety instead of the same artwork three times
    in different sizes.

    Theme preference is ``dark`` because the app's primary chrome is
    dark; light-theme variants tend to be white-on-transparent which
    disappears against the row background. SVG is skipped so the
    frontend can stay on a single `<img>` render path.
    """
    if not has_brand_api():
        return []
    brand = await get_brand(domain)
    if not brand:
        return []

    # Group logos by type, then within each type pick the dark-theme
    # variant if present, otherwise the first available. Order types
    # so the gallery reads icon → symbol → logo (small-to-wide).
    by_type: dict[str, list[dict]] = {}
    for entry in brand.get("logos") or []:
        t = (entry.get("type") or "logo").lower()
        by_type.setdefault(t, []).append(entry)

    out: list[LogoCandidate] = []
    for logo_type in ("icon", "symbol", "logo"):
        entries = by_type.get(logo_type)
        if not entries:
            continue
        # Prefer theme=dark within this type; fall back to anything.
        chosen = next(
            (e for e in entries if (e.get("theme") or "").lower() == "dark"),
            entries[0],
        )
        src = None
        for fmt in chosen.get("formats") or []:
            fmt_name = (fmt.get("format") or "").lower()
            if fmt_name in ("png", "jpeg") and fmt.get("src"):
                src = fmt["src"]
                break
        if not src:
            continue
        out.append(
            LogoCandidate(
                url=src,
                source="brandfetch",
                label=f"Brandfetch · {logo_type}",
            )
        )
    return out


_FAVICONEXTRACTOR = "https://www.faviconextractor.com/favicon/{domain}"


async def _faviconextractor_candidates(domain: str) -> list[LogoCandidate]:
    """faviconextractor returns the site's actual favicon.

    We HEAD both ``?larger=true`` and the default endpoint. If they
    serve byte-identical responses (same ``content-length`` AND same
    ``content-type``) we keep only the larger — duplicate-thumbnail
    spam in the picker is worse than missing one variant. Distinct
    responses (e.g. site declares 32×32 default and 256×256 larger)
    both appear.

    Empty list when both endpoints 404 / time out.
    """
    base_url = _FAVICONEXTRACTOR.format(domain=domain)
    variants = (
        (f"{base_url}?larger=true", "favicon · larger"),
        (base_url, "favicon"),
    )

    async def _probe(client: httpx.AsyncClient, url: str) -> Optional[dict]:
        try:
            resp = await client.head(url)
        except Exception as exc:  # noqa: BLE001
            logger.info("faviconextractor HEAD %s failed: %s", url[:60], exc)
            return None
        if resp.status_code != 200:
            return None
        ctype = (resp.headers.get("content-type") or "").lower()
        # The 404 path serves an SVG placeholder under image/svg+xml,
        # so the status check alone isn't enough — guard on image/*.
        if not ctype.startswith("image/"):
            return None
        return {
            "content_length": resp.headers.get("content-length") or "",
            "content_type": ctype,
        }

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        headers=_HEADERS,
        follow_redirects=True,
    ) as client:
        out: list[LogoCandidate] = []
        seen_fingerprints: set[tuple[str, str]] = set()
        for url, label in variants:
            meta = await _probe(client, url)
            if not meta:
                continue
            # (content-length, content-type) is a cheap-but-strong
            # dedup signal: same bytes count + same MIME on a static
            # CDN-fronted endpoint means same artwork. Avoids both
            # HEAD-on-the-asset hashing (slow) and rendering twice
            # in the gallery (annoying).
            fp = (meta["content_length"], meta["content_type"])
            if fp in seen_fingerprints:
                continue
            seen_fingerprints.add(fp)
            out.append(
                LogoCandidate(url=url, source="faviconextractor", label=label)
            )
    return out


async def _google_favicon_candidates(domain: str) -> list[LogoCandidate]:
    """Single Google s2/favicons URL at 256px — the size param caps at
    that on Google's side, so requesting 128 and 256 yields identical
    bytes (just resized client-side). One entry keeps the picker tidy
    without losing coverage; the default favicon Google has indexed is
    the same regardless of size, only the upscale differs.
    """
    return [
        LogoCandidate(
            url=f"https://www.google.com/s2/favicons?domain={domain}&sz=256",
            source="google",
            label="Google favicon",
        )
    ]


async def resolve_logo_candidates(domain_raw: str) -> list[LogoCandidate]:
    """Public entrypoint. Normalizes the domain, runs all sources in
    parallel for snappier UI, and returns the merged candidate list.

    The Brandfetch entries always appear first (highest quality when
    present), then faviconextractor, then Google. Within Brandfetch we
    keep the order returned by the API (which tends to put icon before
    symbol before logo — sensible for an avatar slot).
    """
    domain = normalize_domain(domain_raw)
    if not domain:
        return []
    import asyncio

    # Run all three sources in parallel — Brandfetch is the slowest
    # (Bearer-auth + JSON parse), faviconextractor needs an HTTP HEAD,
    # Google is pure URL construction. Gather speeds up the slow path
    # without blocking on the fast ones.
    brandfetch_task = asyncio.create_task(_brandfetch_candidates(domain))
    favicon_task = asyncio.create_task(_faviconextractor_candidates(domain))
    google_task = asyncio.create_task(_google_favicon_candidates(domain))
    brandfetch_hits, favicon_hits, google_hits = await asyncio.gather(
        brandfetch_task, favicon_task, google_task, return_exceptions=False
    )
    return [*brandfetch_hits, *favicon_hits, *google_hits]
