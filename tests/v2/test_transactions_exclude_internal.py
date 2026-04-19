"""Tests for the `exclude_internal_transfers` filter on GET /api/transactions.

The "Show internal transactions" toggle on the Transactions page sends
`exclude_internal_transfers=true` when the user wants intra-family
transfers hidden (the default). The repo must add a
`t.transaction_class <> 'internal_transfer'` SQL condition, and the route
must forward the flag straight through to the repo.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.transactions.repo import TransactionsRepository


@pytest.mark.asyncio
async def test_list_transactions_skips_internal_when_flag_true():
    """When `exclude_internal_transfers=True`, the WHERE clause filters
    `transaction_class <> 'internal_transfer'`."""
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetch = AsyncMock(return_value=[])

    repo = TransactionsRepository()
    with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
        await repo.list_transactions(exclude_internal_transfers=True)

    assert conn.fetch.await_count == 1
    sql = conn.fetch.await_args.args[0]
    assert "t.transaction_class <> 'internal_transfer'" in sql


@pytest.mark.asyncio
async def test_list_transactions_includes_internal_by_default():
    """Backward compat: without the flag the internal-transfer condition
    must NOT appear (legacy clients still see every row)."""
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetch = AsyncMock(return_value=[])

    repo = TransactionsRepository()
    with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
        await repo.list_transactions()

    sql = conn.fetch.await_args.args[0]
    assert "transaction_class <> 'internal_transfer'" not in sql


@pytest.mark.asyncio
async def test_list_transactions_false_is_a_no_op():
    """Passing `False` explicitly must not add the filter either — only
    the truthy opt-in trims internal transfers."""
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetch = AsyncMock(return_value=[])

    repo = TransactionsRepository()
    with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
        await repo.list_transactions(exclude_internal_transfers=False)

    sql = conn.fetch.await_args.args[0]
    assert "transaction_class <> 'internal_transfer'" not in sql


@pytest.mark.asyncio
async def test_list_transactions_route_forwards_exclude_flag():
    """Route hand-off: the FastAPI handler must forward the query param
    verbatim to the repo so the toggle actually reaches the SQL layer."""
    from web.transactions.routes import list_transactions

    fake_request = MagicMock()
    fake_request.state.user = {"id": 7, "is_owner": False}

    fake_repo = MagicMock()
    fake_repo.list_transactions = AsyncMock(return_value=[])

    with patch(
        "web.transactions.routes._repo", return_value=fake_repo
    ), patch(
        "web.transactions.routes.reports_include_plaid_sandbox", return_value=True
    ), patch(
        "web.transactions.routes._enrich_many", new_callable=AsyncMock, return_value=[]
    ):
        await list_transactions(
            fake_request,
            month=None,
            account_id=None,
            category_id=None,
            tag_id=None,
            search=None,
            channel=None,
            pending_only=None,
            source=None,
            user_id=None,
            transaction_class=None,
            exclude_internal_transfers=True,
            limit=200,
            offset=0,
        )

    kwargs = fake_repo.list_transactions.call_args.kwargs
    assert kwargs.get("exclude_internal_transfers") is True
