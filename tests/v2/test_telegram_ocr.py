"""
Tests for :mod:`web.telegram.ocr` — the OpenAI vision pipeline that
turns a photo of a receipt into a normalised dict.

The tests cover the pure-function half (``_normalize`` + helpers) and
the size/configuration guards in :func:`extract_receipt`. The OpenAI
call itself is patched out — we don't want the test suite hitting the
network or burning tokens.
"""
from __future__ import annotations

from datetime import date

import pytest

# Import ocr.py directly without triggering ``web.telegram.__init__`` —
# the package init pulls in ``router.py`` which constructs an APIRouter
# at module-import time. The local FastAPI/Starlette pair (0.116.1)
# crashes on that construction with ``Router.__init__() got an
# unexpected keyword argument 'on_startup'``; production runs a slightly
# older Starlette where it works. Tests must not depend on that mismatch.
import importlib.util
import pathlib
import sys

_ocr_path = pathlib.Path(__file__).resolve().parents[2] / "web" / "telegram" / "ocr.py"
_spec = importlib.util.spec_from_file_location("_ocr_under_test", _ocr_path)
ocr = importlib.util.module_from_spec(_spec)
sys.modules["_ocr_under_test"] = ocr
_spec.loader.exec_module(ocr)

_MAX_IMAGE_BYTES = ocr._MAX_IMAGE_BYTES
_coerce_cents = ocr._coerce_cents
_coerce_quantity = ocr._coerce_quantity
_normalize = ocr._normalize
_normalize_lines = ocr._normalize_lines
extract_receipt = ocr.extract_receipt


# ---------------------------------------------------------------------------
# extract_receipt — guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_receipt_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OCR isn't configured"):
        await extract_receipt(b"x")


@pytest.mark.asyncio
async def test_extract_receipt_rejects_oversize(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with pytest.raises(RuntimeError, match="too large"):
        await extract_receipt(b"x" * (_MAX_IMAGE_BYTES + 1))


@pytest.mark.asyncio
async def test_extract_receipt_rejects_empty(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with pytest.raises(RuntimeError, match="empty"):
        await extract_receipt(b"")


# ---------------------------------------------------------------------------
# _normalize — happy path
# ---------------------------------------------------------------------------


def test_normalize_full_payload():
    out = _normalize(
        {
            "merchant_name": "  Brooklyn Fare  ",
            "currency": "usd",
            "date": "2026-04-27",
            "total_cents": 1234,
            "tax_cents": 100,
            "lines": [
                {
                    "description": "Eggs",
                    "quantity": 1,
                    "unit_price_cents": 599,
                    "total_cents": 599,
                }
            ],
        }
    )
    assert out["merchant_name"] == "Brooklyn Fare"
    assert out["currency"] == "USD"
    assert out["date"] == date(2026, 4, 27)
    assert out["total_cents"] == 1234
    assert out["tax_cents"] == 100
    assert out["lines"] == [
        {
            "description": "Eggs",
            "quantity": 1.0,
            "unit_price_cents": 599,
            "total_cents": 599,
        }
    ]


def test_normalize_empty_merchant_becomes_none():
    out = _normalize({"merchant_name": "  "})
    assert out["merchant_name"] is None


def test_normalize_currency_strips_garbage():
    """Models occasionally emit ``"USD$"`` or ``"$"`` for the currency
    field. We sanitise to ISO-4217-ish: alpha-only, ≤ 3 chars, defaulting
    to USD if nothing readable comes out."""
    assert _normalize({"currency": "USD$"})["currency"] == "USD"
    assert _normalize({"currency": "$"})["currency"] == "USD"
    assert _normalize({"currency": "EurO"})["currency"] == "EUR"
    assert _normalize({})["currency"] == "USD"


def test_normalize_bad_date_becomes_none():
    assert _normalize({"date": "not-a-date"})["date"] is None
    assert _normalize({"date": None})["date"] is None
    assert _normalize({"date": 12345})["date"] is None


def test_normalize_lines_skip_invalid_rows():
    """Rows missing a description or total are dropped silently — better
    to ship a partial receipt than crash on one bad line."""
    out = _normalize_lines(
        [
            {"description": "Eggs", "total_cents": 599},
            {"description": "", "total_cents": 100},  # empty desc
            {"description": "Milk"},                   # missing total
            "not a dict",                              # garbage row
            {"description": "Bread", "total_cents": "abc"},  # bad total
        ]
    )
    assert len(out) == 1
    assert out[0]["description"] == "Eggs"


def test_normalize_lines_handles_non_list_input():
    assert _normalize_lines(None) == []
    assert _normalize_lines("not a list") == []
    assert _normalize_lines({"description": "Eggs"}) == []


# ---------------------------------------------------------------------------
# _coerce_cents / _coerce_quantity edge cases
# ---------------------------------------------------------------------------


def test_coerce_cents_handles_floats():
    """Direct floats and float-shaped strings both round to the nearest
    int. Note Python uses banker's rounding (``round(12.5) == 12``) — the
    OCR layer accepts that as standard financial behaviour."""
    assert _coerce_cents(12.7) == 13
    assert _coerce_cents(13.4) == 13
    assert _coerce_cents("12") == 12
    assert _coerce_cents("12.7") == 13
    # Banker's rounding: 12.5 → 12 (rounds half to even). Pinned so the
    # next person who tweaks the coercer doesn't accidentally introduce
    # naive round-half-up that flips this column by a cent.
    assert _coerce_cents("12.5") == 12
    assert _coerce_cents("13.5") == 14


def test_coerce_cents_returns_none_for_garbage():
    assert _coerce_cents(None) is None
    assert _coerce_cents("abc") is None
    assert _coerce_cents([]) is None


def test_coerce_cents_rejects_bool():
    """``True`` is an int subclass so naive ``int(True)`` returns 1.
    The OCR layer must NOT silently book a $0.01 line item if the model
    emits ``"total_cents": true``. Same for the quantity coercer."""
    assert _coerce_cents(True) is None
    assert _coerce_cents(False) is None
    assert _coerce_quantity(True) is None
