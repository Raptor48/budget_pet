"""
Regression tests for :meth:`BotRepository.create_receipt`.

The original incident (2026-04-27) was an asyncpg ``DataError`` because
``raw_ocr_json`` was passed as a ``dict`` without serialisation. After
the JSONB codec landed in :mod:`web.db`, the fix is a single contract:
the repo passes the dict straight through to ``conn.fetchrow``, the
codec serialises, and the row inserts. These tests pin that the dict
travels untouched and the SQL bind order matches the column order.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.v2.conftest import make_mock_pool, make_record


@pytest.fixture
def repo(monkeypatch):
    from web.bot_api.repo import BotRepository

    repo_instance = BotRepository()
    return repo_instance


def _make_conn_with_row(row):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    conn.execute = AsyncMock()
    # ``async with conn.transaction(): ...`` requires a context manager —
    # asyncpg's transaction() returns one synchronously, then awaits in
    # __aenter__/__aexit__.
    txn_ctx = MagicMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_ctx)
    return conn


@pytest.mark.asyncio
async def test_create_receipt_passes_dict_directly_to_jsonb_column(monkeypatch, repo):
    """The previously-broken contract: ``raw_ocr_json`` is a dict and
    asyncpg must NOT see a ``json.dumps()`` call at this layer — the
    pool codec handles serialisation."""
    fake_row = make_record(
        id=42,
        user_id=1,
        transaction_id=None,
        merchant_name="Brooklyn Fare",
    )
    conn = _make_conn_with_row(fake_row)
    monkeypatch.setattr(
        "web.bot_api.repo.get_pool",
        AsyncMock(return_value=make_mock_pool(conn)),
    )

    parsed_payload = {
        "merchant_name": "Brooklyn Fare",
        "currency": "USD",
        "total_cents": 1234,
        "lines": [{"description": "Eggs", "total_cents": 599}],
    }
    out = await repo.create_receipt(
        user_id=1,
        image_data=b"jpeg-bytes",
        image_mime="image/jpeg",
        merchant_name="Brooklyn Fare",
        receipt_date=date(2026, 4, 27),
        total_cents=1234,
        tax_cents=None,
        currency="USD",
        raw_ocr_json=parsed_payload,
        lines=parsed_payload["lines"],
    )
    assert out["id"] == 42

    # Verify the bind: $10 must be the dict, not a serialised string.
    # Column order in the INSERT is: user_id, transaction_id,
    # merchant_name, receipt_date, total_cents, tax_cents, currency,
    # image_data, image_mime, raw_ocr_json, parse_status — so $10 is at
    # index 10 in args (1-indexed) / args[10] (0-indexed: SQL is args[1]).
    insert_call = conn.fetchrow.await_args
    bound_args = insert_call.args
    # bound_args[0] is the SQL string, bound_args[1..N] are the params.
    assert bound_args[0].lstrip().startswith("INSERT INTO receipts")
    raw_ocr_param = bound_args[10]
    assert isinstance(raw_ocr_param, dict), (
        "raw_ocr_json must be passed as a dict — the pool codec handles "
        "JSON serialisation. If this assertion fails, somebody re-added "
        "json.dumps() at the call site and the pool codec will double-"
        "encode it into a string-of-a-string blob."
    )
    assert raw_ocr_param["merchant_name"] == "Brooklyn Fare"


@pytest.mark.asyncio
async def test_create_receipt_inserts_lines_in_order(monkeypatch, repo):
    fake_row = make_record(id=7)
    conn = _make_conn_with_row(fake_row)
    monkeypatch.setattr(
        "web.bot_api.repo.get_pool",
        AsyncMock(return_value=make_mock_pool(conn)),
    )

    lines = [
        {"description": "Eggs", "total_cents": 599, "quantity": 1.0},
        {"description": "Milk", "total_cents": 399, "quantity": 1.0},
    ]
    await repo.create_receipt(
        user_id=1,
        image_data=b"x",
        image_mime="image/jpeg",
        raw_ocr_json={},
        lines=lines,
    )
    # Two execute() calls for two lines, in order with line_number 1, 2.
    assert conn.execute.await_count == 2
    line1 = conn.execute.await_args_list[0].args
    line2 = conn.execute.await_args_list[1].args
    assert line1[2] == 1 and line1[3] == "Eggs"
    assert line2[2] == 2 and line2[3] == "Milk"


@pytest.mark.asyncio
async def test_create_receipt_rejects_invalid_parse_status(repo):
    with pytest.raises(ValueError, match="parse_status"):
        await repo.create_receipt(
            user_id=1,
            image_data=b"x",
            image_mime="image/jpeg",
            raw_ocr_json={},
            parse_status="WHATEVER",
        )


@pytest.mark.asyncio
async def test_create_receipt_handles_none_raw_ocr_json(monkeypatch, repo):
    """Sanity: if no OCR was run (manual upload, future feature), passing
    ``None`` must still work."""
    fake_row = make_record(id=99)
    conn = _make_conn_with_row(fake_row)
    monkeypatch.setattr(
        "web.bot_api.repo.get_pool",
        AsyncMock(return_value=make_mock_pool(conn)),
    )
    out = await repo.create_receipt(
        user_id=1,
        image_data=b"x",
        image_mime="image/jpeg",
        raw_ocr_json=None,
    )
    assert out["id"] == 99
    insert_call = conn.fetchrow.await_args
    raw_ocr_param = insert_call.args[10]
    assert raw_ocr_param is None
