"""
Image normalisation for receipts arriving via Telegram.

We resize and recompress before storage *and* before OCR for two reasons:

1. **Postgres footprint.** A 4 MB iPhone shot in BYTEA balloons backups
   and slows row reads. 1600 px max edge + JPEG q85 cuts that to
   ~350 KB without measurable OCR quality loss — gpt-4o-mini's vision
   pipeline tiles images at 512 px anyway.
2. **OCR cost + latency.** OpenAI charges per image megapixel and the
   upload itself is the bottleneck on a slow phone. Smaller image,
   faster turnaround.

Stripping EXIF is a privacy win on top — phones embed GPS coordinates
into raw shots and we have no business storing the user's home address
in our DB.

When Pillow is unavailable (dev env without the binary wheel) we
silently fall back to the original bytes — no resize, no crash. The
production Dockerfile pins Pillow in ``requirements.txt`` so this fallback
only matters for local hacking.
"""
from __future__ import annotations

import io
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# 1600 px on the longest edge keeps a 3:4 receipt at ~1100×1467 — every
# line item is still legible to the human eye AND the model. Going lower
# (e.g. 1024 px) starts losing tiny "$0.99" digits on dense receipts.
DEFAULT_MAX_EDGE = 1600

# JPEG quality 85 is the sweet spot for photographic content — visually
# indistinguishable from 95 but ~30% smaller. Below 80 starts to show
# blocking on text edges, which costs OCR accuracy.
DEFAULT_QUALITY = 85


def normalise_receipt_image(
    image_bytes: bytes,
    *,
    max_edge: int = DEFAULT_MAX_EDGE,
    quality: int = DEFAULT_QUALITY,
) -> Tuple[bytes, str]:
    """Return (resized_bytes, mime_type).

    Always returns JPEG bytes regardless of input format. EXIF metadata
    is stripped. If the image is already smaller than ``max_edge`` we
    still recompress to JPEG to normalise format (Telegram occasionally
    forwards HEIC or PNG; the storage layer expects JPEG).

    Falls back to the original bytes + ``image/jpeg`` if Pillow isn't
    importable. The OCR pipeline still works either way; only the
    storage footprint suffers.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover — dev env without Pillow
        logger.warning("Pillow not available; storing receipt at original size")
        return image_bytes, "image/jpeg"

    if not image_bytes:
        return image_bytes, "image/jpeg"

    try:
        with Image.open(io.BytesIO(image_bytes)) as src:
            # exif_transpose() honours the camera's orientation tag so a
            # photo shot in landscape doesn't show up sideways. PIL doesn't
            # do this automatically — it just respects the raw pixel grid.
            img = ImageOps.exif_transpose(src)
            # Discard the alpha channel — JPEG can't represent it and
            # Pillow would crash with OSError on save() otherwise.
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            elif img.mode != "RGB":
                # Grayscale ("L"), CMYK and friends — coerce to RGB so the
                # JPEG encoder is happy.
                img = img.convert("RGB")

            w, h = img.size
            longest = max(w, h)
            if longest > max_edge:
                scale = max_edge / float(longest)
                new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
                # LANCZOS keeps text edges crisp at high downscale ratios
                # (3024→1100 in the iPhone case). BILINEAR would soften
                # the smallest digits enough to hurt OCR.
                img = img.resize(new_size, Image.LANCZOS)

            out = io.BytesIO()
            # ``optimize=True`` lets Pillow run a second pass to shrink
            # Huffman tables — a few extra ms per save for ~5% size win.
            # ``progressive=True`` is friendlier when serving the image
            # over the wire (browsers render coarsely first).
            img.save(
                out,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )
            return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001 — never break the upload path
        logger.exception("normalise_receipt_image failed; using original bytes")
        return image_bytes, "image/jpeg"
