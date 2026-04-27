"""
Receipt OCR — single-call vision pipeline using OpenAI gpt-4o-mini.

Returns a dict with ``merchant_name``, ``total_cents``, optional
``tax_cents``, ISO date, and a ``lines`` list. Lines are stored verbatim
in ``receipt_lines`` so the frontend can show "what did I buy in Whole
Foods last week" without re-running OCR.

When ``OPENAI_API_KEY`` is unset, ``extract_receipt`` raises
:class:`RuntimeError` with a friendly message — the bot surfaces it to
the user.
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


def _ocr_enabled() -> bool:
    return bool((os.getenv("OPENAI_API_KEY") or "").strip())


async def extract_receipt(image_bytes: bytes) -> Dict[str, Any]:
    if not _ocr_enabled():
        raise RuntimeError(
            "OCR isn't configured. Set OPENAI_API_KEY on the server."
        )
    return await asyncio.to_thread(_run_openai_vision, image_bytes)


def _run_openai_vision(image_bytes: bytes) -> Dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    encoded = base64.b64encode(image_bytes).decode("ascii")
    image_url = f"data:image/jpeg;base64,{encoded}"
    resp = client.chat.completions.create(
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
        timeout=45,
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OCR returned invalid JSON: {exc}") from exc
    return _normalize(data)


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    out["merchant_name"] = (data.get("merchant_name") or "").strip() or None
    out["currency"] = (data.get("currency") or "USD").upper()
    raw_date = data.get("date")
    parsed_date: Optional[date] = None
    if raw_date:
        try:
            parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            parsed_date = None
    out["date"] = parsed_date
    out["total_cents"] = _coerce_cents(data.get("total_cents"))
    out["tax_cents"] = _coerce_cents(data.get("tax_cents"))
    out["lines"] = _normalize_lines(data.get("lines") or [])
    return out


def _coerce_cents(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(round(float(val)))
        except Exception:
            return None


def _normalize_lines(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
