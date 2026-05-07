"""
Regression tests for the ``delete_linked_cash`` option on receipt
deletion + detachment.

Background: deleting (or detaching) a receipt that was attached to a
manual cash transaction we created via "Log as cash" used to leave the
cash row standing in the wallet. Users only noticed days later when
their spend totals didn't match. The flag — driven by a checkbox in the
smart confirm dialog — opts into removing that orphan cash row in the
same DB transaction.

Crucially the flag must NEVER delete a Plaid-imported transaction,
even if the FE somehow sets it to true. Plaid is the source of truth
and the row would resurrect on next sync anyway, so we'd be telling
the user one thing and silently doing another.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.v2.conftest import make_mock_pool, make_record


def _make_conn(probe_row, delete_count=" 1"):
    """Connection that returns ``probe_row`` for the JOIN probe and
    a successful DELETE for everything else.

    asyncpg's ``conn.transaction()`` returns a context manager
    synchronously and awaits in __aenter__/__aexit__ — easy to fake.
    """
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=probe_row)
    conn.execute = AsyncMock(return_value=f"DELETE{delete_count}")
    txn_ctx = MagicMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_ctx)
    return conn


@pytest.fixture
def repo():
    from web.bot_api.repo import BotRepository

    return BotRepository()


# ---------------------------------------------------------------------------
# delete_receipt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_receipt_with_flag_drops_manual_cash_tx(monkeypatch, repo):
    """Receipt linked to a manual cash tx + flag=True → DELETE both."""
    probe = make_record(transaction_id=42, source="manual", is_bank_tx=False)
    conn = _make_conn(probe)
    monkeypatch.setattr(
        "web.bot_api.repo.get_pool",
        AsyncMock(return_value=make_mock_pool(conn)),
    )

    result = await repo.delete_receipt(
        user_id=1, receipt_id=99, delete_linked_cash=True
    )
    assert result is True
    # Two DELETEs: receipt, then transaction.
    assert conn.execute.await_count == 2
    delete_sqls = [call.args[0] for call in conn.execute.await_args_list]
    assert any("DELETE FROM receipts" in sql for sql in delete_sqls)
    assert any("DELETE FROM transactions" in sql for sql in delete_sqls)


@pytest.mark.asyncio
async def test_delete_receipt_without_flag_leaves_cash_tx(monkeypatch, repo):
    probe = make_record(transaction_id=42, source="manual", is_bank_tx=False)
    conn = _make_conn(probe)
    monkeypatch.setattr(
        "web.bot_api.repo.get_pool",
        AsyncMock(return_value=make_mock_pool(conn)),
    )

    await repo.delete_receipt(user_id=1, receipt_id=99, delete_linked_cash=False)
    # Only the receipt DELETE — the cash tx is preserved (default
    # behaviour, backwards-compatible with pre-flag callers).
    assert conn.execute.await_count == 1
    assert "DELETE FROM receipts" in conn.execute.await_args_list[0].args[0]


@pytest.mark.asyncio
async def test_delete_receipt_flag_never_deletes_plaid_tx(monkeypatch, repo):
    """Even if flag=True, Plaid-imported (is_bank_tx=True) transactions
    must NOT be deleted. Plaid is the source of truth — deleting from
    Postgres just causes the row to reappear on next sync."""
    probe = make_record(transaction_id=77, source="plaid", is_bank_tx=True)
    conn = _make_conn(probe)
    monkeypatch.setattr(
        "web.bot_api.repo.get_pool",
        AsyncMock(return_value=make_mock_pool(conn)),
    )

    await repo.delete_receipt(user_id=1, receipt_id=99, delete_linked_cash=True)
    assert conn.execute.await_count == 1
    assert "DELETE FROM receipts" in conn.execute.await_args_list[0].args[0]


@pytest.mark.asyncio
async def test_delete_receipt_flag_skipped_when_unlinked(monkeypatch, repo):
    """Receipt with no transaction_id — flag is a no-op."""
    probe = make_record(transaction_id=None, source=None, is_bank_tx=None)
    conn = _make_conn(probe)
    monkeypatch.setattr(
        "web.bot_api.repo.get_pool",
        AsyncMock(return_value=make_mock_pool(conn)),
    )

    await repo.delete_receipt(user_id=1, receipt_id=99, delete_linked_cash=True)
    assert conn.execute.await_count == 1


@pytest.mark.asyncio
async def test_delete_receipt_returns_false_for_unknown_id(monkeypatch, repo):
    conn = _make_conn(probe_row=None)
    monkeypatch.setattr(
        "web.bot_api.repo.get_pool",
        AsyncMock(return_value=make_mock_pool(conn)),
    )

    result = await repo.delete_receipt(user_id=1, receipt_id=999, delete_linked_cash=True)
    assert result is False
    # No deletes attempted — short-circuit on the probe miss.
    assert conn.execute.await_count == 0


# ---------------------------------------------------------------------------
# link_receipt (detach with cash cleanup)
# ---------------------------------------------------------------------------


def _make_link_conn(prev_row):
    """Detach path: probe → UPDATE receipt → optional DELETE tx →
    final SELECT to refresh."""
    conn = AsyncMock()
    # fetchrow is called multiple times (prev probe, UPDATE returning,
    # then twice in get_receipt). We use side_effect to sequence.
    update_returning = make_record(id=99)
    get_receipt_row = make_record(
        id=99,
        transaction_id=None,
        merchant_name="Test",
        receipt_date=None,
        total_cents=1234,
        tax_cents=None,
        currency="USD",
        parse_status="parsed",
        image_mime="image/jpeg",
        created_at="2026-04-27T19:08:00Z",
        has_image=True,
        linked_is_manual_cash=False,
    )
    conn.fetchrow = AsyncMock(
        side_effect=[prev_row, update_returning, get_receipt_row]
    )
    conn.fetch = AsyncMock(return_value=[])  # no lines
    conn.execute = AsyncMock(return_value="DELETE 1")
    txn_ctx = MagicMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_ctx)
    return conn


@pytest.mark.asyncio
async def test_link_detach_with_flag_drops_manual_cash_tx(monkeypatch, repo):
    prev = make_record(prev_txn_id=42, source="manual", is_bank_tx=False)
    conn = _make_link_conn(prev)
    monkeypatch.setattr(
        "web.bot_api.repo.get_pool",
        AsyncMock(return_value=make_mock_pool(conn)),
    )

    result = await repo.link_receipt(
        user_id=1, receipt_id=99, transaction_id=None, delete_linked_cash=True
    )
    assert result is not None
    # The single DELETE call must be the cash transaction (the receipt
    # itself is UPDATEd via fetchrow, not DELETE).
    assert conn.execute.await_count == 1
    assert "DELETE FROM transactions" in conn.execute.await_args_list[0].args[0]


@pytest.mark.asyncio
async def test_link_detach_without_flag_leaves_cash_tx(monkeypatch, repo):
    prev = make_record(prev_txn_id=42, source="manual", is_bank_tx=False)
    conn = _make_link_conn(prev)
    monkeypatch.setattr(
        "web.bot_api.repo.get_pool",
        AsyncMock(return_value=make_mock_pool(conn)),
    )

    await repo.link_receipt(
        user_id=1, receipt_id=99, transaction_id=None, delete_linked_cash=False
    )
    # No DELETE — only the receipt UPDATE happened (via fetchrow).
    assert conn.execute.await_count == 0


@pytest.mark.asyncio
async def test_link_attach_does_not_delete_anything(monkeypatch, repo):
    """Attaching (not detaching) must never delete, even with flag=True."""
    prev = make_record(prev_txn_id=42, source="manual", is_bank_tx=False)
    conn = _make_link_conn(prev)
    monkeypatch.setattr(
        "web.bot_api.repo.get_pool",
        AsyncMock(return_value=make_mock_pool(conn)),
    )

    await repo.link_receipt(
        user_id=1,
        receipt_id=99,
        transaction_id=12345,  # attaching to a new tx
        delete_linked_cash=True,  # honoured only when detaching
    )
    assert conn.execute.await_count == 0


@pytest.mark.asyncio
async def test_link_detach_flag_never_deletes_plaid_tx(monkeypatch, repo):
    """Flag honoured only when previous link was a manual cash tx."""
    prev = make_record(prev_txn_id=42, source="plaid", is_bank_tx=True)
    conn = _make_link_conn(prev)
    monkeypatch.setattr(
        "web.bot_api.repo.get_pool",
        AsyncMock(return_value=make_mock_pool(conn)),
    )

    await repo.link_receipt(
        user_id=1, receipt_id=99, transaction_id=None, delete_linked_cash=True
    )
    assert conn.execute.await_count == 0
