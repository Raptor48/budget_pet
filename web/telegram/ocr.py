"""
Receipt OCR — single-call vision pipeline using OpenAI gpt-4o-mini.

Returns a dict with ``merchant_name``, ``total_cents``, optional
``tax_cents``, ISO date, currency and a ``lines`` list. Lines are stored
verbatim in ``receipt_lines`` so the frontend can show "what did I buy
in Whole Foods last week" without re-running OCR.

Failure modes — all surface as :class:`RuntimeError` with a friendly
message so :func:`on_photo_message` can show them straight to the user
without a stack trace:

* ``OPENAI_API_KEY`` unset → "OCR isn't configured."
* OpenAI rate limit / 429 → "OCR is busy, try again in a minute."
* OpenAI timeout (>``OPENAI_OCR_TIMEOUT`` sec) → "OCR timed out."
* OpenAI server error (5xx) → one automatic retry, then "OCR backend
  is having a moment."
* JSON parse failure → "OCR returned invalid JSON" (model misbehaved).
* Image too large for the API (>20 MB) → caught up-front, no API call
  wasted, "Receipt photo is too large…".

The single ``response_format={'type': 'json_object'}`` flag plus
``temperature=0`` keeps the model deterministic and JSON-only — we
never have to scrape prose.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_PROMPT = """You receive a photo of a paper receipt. Return STRICT JSON with:
{
  "merchant_name": str | null,         // best-guess merchant
  "date": "YYYY-MM-DD" | null,         // receipt date if visible
  "currency": "USD" | "EUR" | str,
  "total_cents": int,                  // grand total in cents
  "tax_cents": int | null,             // tax/VAT in cents if shown
  "lines": [                            // one entry per non-discount line item
    {
      "description": str,
      "quantity": float | null,
      "unit_price_cents": int | null,
      "total_cents": int
    }
  ]
}
If you cannot read the total, return total_cents = 0 and an empty lines array.
Do NOT include any prose around the JSON.
"""

# OpenAI's vision endpoint accepts images up to 20 MB encoded. Telegram
# caps photos at 10 MB compressed, so this is mostly defence-in-depth
# for the rare path where the file slips through (e.g. a manual upload
# via the future receipt-upload route).
_MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _ocr_enabled() -> bool:
    return bool((os.getenv("OPENAI_API_KEY") or "").strip())


def _ocr_timeout() -> float:
    try:
        return float(os.getenv("OPENAI_OCR_TIMEOUT", "45"))
    except ValueError:
        return 45.0


async def extract_receipt(image_bytes: bytes) -> Dict[str, Any]:
    if not _ocr_enabled():
        raise RuntimeError(
            "OCR isn't configured. Set OPENAI_API_KEY on the server."
        )
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        mb = len(image_bytes) / (1024 * 1024)
        raise RuntimeError(
            f"Receipt photo is too large ({mb:.1f} MB). Max is 20 MB."
        )
    if not image_bytes:
        raise RuntimeError("Receipt photo is empty.")
    return await asyncio.to_thread(_run_openai_vision, image_bytes)


def _run_openai_vision(image_bytes: bytes) -> Dict[str, Any]:
    # Local import keeps cold-start light when OCR is unused; also
    # allows tests to patch ``openai.OpenAI`` without monkey-patching at
    # module-import time.
    from openai import OpenAI

    try:
        from openai import (
            APIConnectionError,
            APIError,
            APITimeoutError,
            RateLimitError,
        )
    except ImportError:  # pragma: no cover — older openai sdk fallback
        APIConnectionError = APIError = APITimeoutError = RateLimitError = Exception

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    encoded = base64.b64encode(image_bytes).decode("ascii")
    image_url = f"data:image/jpeg;base64,{encoded}"

    def _call_once():
        return client.chat.completions.create(
            model=os.getenv("OPENAI_OCR_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            response_format={"type": "json_object"},
            temperature=0,
            timeout=_ocr_timeout(),
        )

    # One automatic retry on transient backend issues. Anything else
    # (auth failures, prompt-too-long, etc.) bubbles immediately so the
    # user sees the real cause rather than two slow attempts in a row.
    try:
        resp = _call_once()
    except RateLimitError as exc:
        logger.warning("OpenAI rate limit on first attempt: %s", exc)
        raise RuntimeError("OCR is busy right now, try again in a minute.") from exc
    except APITimeoutError as exc:
        raise RuntimeError(
            f"OCR timed out after {_ocr_timeout():.0f}s. Try a smaller photo."
        ) from exc
    except APIConnectionError as exc:
        logger.warning("OpenAI connection error, retrying once: %s", exc)
        try:
            resp = _call_once()
        except (APIError, APIConnectionError) as exc2:
            raise RuntimeError("OCR backend is unreachable right now.") from exc2
    except APIError as exc:
        # 4xx are caller's problem — surface verbatim. 5xx → one retry.
        status = getattr(exc, "status_code", None)
        if status and 500 <= int(status) < 600:
            logger.warning("OpenAI %s, retrying once: %s", status, exc)
            try:
                resp = _call_once()
            except APIError as exc2:
                raise RuntimeError("OCR backend is having a moment.") from exc2
        else:
            raise RuntimeError(f"OCR rejected the photo: {exc}") from exc

    raw = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Most often a model that briefly forgot the json_object contract.
        logger.warning("OCR returned non-JSON: %r", raw[:200])
        raise RuntimeError(f"OCR returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("OCR returned a non-object JSON payload.")
    return _normalize(data)


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    out["merchant_name"] = (data.get("merchant_name") or "").strip() or None
    raw_currency = (data.get("currency") or "USD").strip().upper()
    # Guard against the model emitting "USD$" or a rogue 4-letter string —
    # the receipts.currency column is TEXT, but downstream FE assumes ISO
    # 4217 so we keep alpha-only and ≤ 3 chars.
    cleaned = "".join(ch for ch in raw_currency if ch.isalpha())[:3]
    out["currency"] = cleaned or "USD"
    raw_date = data.get("date")
    parsed_date: Optional[date] = None
    if raw_date:
        try:
            parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            parsed_date = None
    out["date"] = parsed_date
    out["total_cents"] = _coerce_cents(data.get("total_cents"))
    out["tax_cents"] = _coerce_cents(data.get("tax_cents"))
    out["lines"] = _normalize_lines(data.get("lines") or [])
    return out


def _coerce_cents(val: Any) -> Optional[int]:
    # ``bool`` subclasses ``int``; exclude up-front so ``True`` isn't
    # silently booked as $0.01.
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        # Always round; raw ``int(12.7)`` truncates to 12 and silently
        # loses a cent. The OCR model occasionally emits floats for
        # totals it had to do arithmetic on (e.g. "tax + subtotal").
        return int(round(val))
    try:
        return int(round(float(val)))
    except (TypeError, ValueError):
        return None


def _normalize_lines(rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        desc = (r.get("description") or "").strip()
        total = _coerce_cents(r.get("total_cents"))
        if not desc or total is None:
            continue
        out.append(
            {
                "description": desc[:200],
                "quantity": _coerce_quantity(r.get("quantity")),
                "unit_price_cents": _coerce_cents(r.get("unit_price_cents")),
                "total_cents": total,
            }
        )
    return out


def _coerce_quantity(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
