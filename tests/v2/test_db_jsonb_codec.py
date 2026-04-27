"""
Regression tests for the JSONB/JSON codec registered in
:mod:`web.db._init_connection`.

The smoking gun that motivated this codec was a Telegram-bot OCR crash
(see incident on 2026-04-27) where ``raw_ocr_json={'merchant': …}`` was
passed straight to a JSONB column without ``json.dumps()``, raising
``asyncpg.exceptions.DataError: ... (expected str, got dict)``. The
codec normalises every JSONB write site so any caller can pass a dict
directly. These tests pin that contract.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from web.db import _init_connection, _jsonb_decode, _jsonb_encode


@pytest.mark.asyncio
async def test_init_connection_registers_json_and_jsonb_codecs():
    conn = AsyncMock()
    await _init_connection(conn)
    assert conn.set_type_codec.await_count == 2
    type_names = {call.args[0] for call in conn.set_type_codec.await_args_list}
    assert type_names == {"json", "jsonb"}
    for call in conn.set_type_codec.await_args_list:
        assert call.kwargs.get("schema") == "pg_catalog"
        assert call.kwargs.get("encoder") is _jsonb_encode
        assert call.kwargs.get("decoder") is _jsonb_decode


def test_encoder_serialises_dict():
    payload = {"merchant_name": "Brooklyn Fare", "total_cents": 1234}
    encoded = _jsonb_encode(payload)
    assert isinstance(encoded, str)
    # Must roundtrip cleanly — the asyncpg encoder runs once per write.
    assert json.loads(encoded) == payload


def test_encoder_serialises_list():
    payload = [{"description": "Eggs", "total_cents": 599}]
    encoded = _jsonb_encode(payload)
    assert json.loads(encoded) == payload


def test_encoder_passes_through_pre_serialised_strings():
    """Backwards-compat for legacy call sites that already do ``json.dumps()``.

    Before the codec, ``web/audit/repo.py``, ``web/notifications/queue.py``
    and friends used ``json.dumps(...)`` + ``$N::jsonb``. After the codec
    those strings must NOT be re-encoded (which would produce a double-
    encoded ``"\"...\""``) — they pass through verbatim.
    """
    pre_serialised = json.dumps({"already": "json"})
    encoded = _jsonb_encode(pre_serialised)
    assert encoded == pre_serialised
    # Critically, the result is parseable as the ORIGINAL dict, not as
    # a string-of-a-string.
    assert json.loads(encoded) == {"already": "json"}


def test_encoder_handles_non_json_native_types_via_default_str():
    """Dates / Decimals would normally crash json.dumps with TypeError.

    The codec sets ``default=str`` so OCR payloads (which carry a
    ``datetime.date``) and notification builders (which sometimes
    carry ``Decimal``) survive the roundtrip — string is good enough for
    storage, the FE never round-trips it back into Python.
    """
    payload = {"date": date(2026, 4, 27), "amount": Decimal("12.34")}
    encoded = _jsonb_encode(payload)
    assert json.loads(encoded) == {"date": "2026-04-27", "amount": "12.34"}


def test_encoder_emits_unicode_not_escaped():
    """Russian merchant names should not be ``\\u04XX``-escaped — JSONB
    stores the raw UTF-8 either way, but unescaped output is easier to
    grep in pg_dump."""
    payload = {"merchant_name": "Магнит"}
    encoded = _jsonb_encode(payload)
    assert "Магнит" in encoded


def test_decoder_parses_json_string():
    raw = '{"foo": "bar", "n": 7}'
    decoded = _jsonb_decode(raw)
    assert decoded == {"foo": "bar", "n": 7}


def test_decoder_parses_array():
    raw = "[1, 2, 3]"
    assert _jsonb_decode(raw) == [1, 2, 3]
