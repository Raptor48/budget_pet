"""
Plaid item removal: ``?purge=true`` vs ``?purge=false`` (default).

Covers both the repository methods (``purge_item`` + ``get_item_data_summary``)
and the route wiring, so a ``DELETE /api/plaid/items/{item_id}`` with
``purge=true`` deletes transactions + accounts + streams + holdings while
``purge=false`` only removes the ``plaid_items`` row (legacy behaviour).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.plaid.repo import PlaidRepository


class FakeTx:
    """Async context manager that mimics ``async with conn.transaction():``."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _configure_conn_for_purge(account_ids, tx_ids):
    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=FakeTx())
    account_rows = [{"id": aid} for aid in account_ids]
    tx_rows = [{"id": tid} for tid in tx_ids]

    async def fetch(sql, *args):
        if "FROM accounts WHERE plaid_item_id" in sql:
            return account_rows
        if "FROM transactions" in sql and "account_id = ANY" in sql:
            return tx_rows
        return []

    conn.fetch = AsyncMock(side_effect=fetch)

    execute_calls: list[str] = []

    async def execute(sql, *args):
        execute_calls.append(sql)
        if "DELETE FROM recurring_streams" in sql:
            return "DELETE 4"
        if "DELETE FROM accounts WHERE id = ANY" in sql:
            return f"DELETE {len(account_ids)}"
        if "DELETE FROM plaid_items" in sql:
            return "DELETE 1"
        return "DELETE 0"

    conn.execute = AsyncMock(side_effect=execute)
    return conn, execute_calls


@pytest.mark.asyncio
async def test_purge_item_deletes_all_related_data():
    repo = PlaidRepository()
    conn, execute_calls = _configure_conn_for_purge(
        account_ids=[11, 12], tx_ids=[101, 102, 103]
    )
    pool = make_mock_pool(conn)

    with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)):
        summary = await repo.purge_item("item-xyz")

    assert summary["transactions_deleted"] == 3
    assert summary["accounts_deleted"] == 2
    assert summary["recurring_streams_deleted"] == 4
    assert summary["plaid_items_deleted"] == 1

    joined = "\n".join(execute_calls)
    assert "DELETE FROM transaction_tags" in joined
    assert "DELETE FROM transaction_splits" in joined
    assert "DELETE FROM transactions" in joined
    assert "DELETE FROM recurring_streams" in joined
    assert "DELETE FROM investment_holdings" in joined
    assert "DELETE FROM securities" in joined
    assert "DELETE FROM plaid_sync_log" in joined
    assert "DELETE FROM accounts" in joined
    assert "DELETE FROM plaid_items" in joined


@pytest.mark.asyncio
async def test_purge_item_with_no_accounts_still_removes_item():
    """Orphaned plaid_items (no accounts) must still be deletable via purge."""
    repo = PlaidRepository()
    conn, execute_calls = _configure_conn_for_purge(account_ids=[], tx_ids=[])
    pool = make_mock_pool(conn)

    with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)):
        summary = await repo.purge_item("item-empty")

    assert summary["transactions_deleted"] == 0
    assert summary["accounts_deleted"] == 0
    assert summary["plaid_items_deleted"] == 1
    joined = "\n".join(execute_calls)
    # Still must clean sync log and the item row itself even when no accounts exist.
    assert "DELETE FROM plaid_sync_log" in joined
    assert "DELETE FROM plaid_items" in joined
    # Must NOT attempt transaction/account deletion when there are no accounts.
    assert "DELETE FROM transactions WHERE id = ANY" not in joined
    assert "DELETE FROM accounts WHERE id = ANY" not in joined


@pytest.mark.asyncio
async def test_get_item_data_summary_returns_counts():
    repo = PlaidRepository()
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    fetchrow_calls: list[str] = []

    async def fetchrow(sql, *args):
        fetchrow_calls.append(sql)
        if "FROM accounts" in sql:
            return {"c": 3}
        if "FROM transactions" in sql:
            return {"c": 1200}
        return None

    conn.fetchrow = AsyncMock(side_effect=fetchrow)

    with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)):
        summary = await repo.get_item_data_summary("item-xyz")

    assert summary == {"accounts_count": 3, "transactions_count": 1200}
    joined = "\n".join(fetchrow_calls)
    # Only Plaid-sourced transactions are counted; cash/manual must not inflate the number.
    assert "source IN ('plaid', 'plaid_sandbox')" in joined


@pytest.mark.asyncio
async def test_delete_item_route_default_keeps_data():
    from web.plaid import routes as plaid_routes

    fake_repo = MagicMock()
    fake_repo.get_item = AsyncMock(return_value={"item_id": "i1", "user_id": 7})
    fake_repo.delete_item = AsyncMock(return_value=True)
    fake_repo.purge_item = AsyncMock()

    request = MagicMock()
    request.state.user = {"id": 7, "is_owner": False}

    with patch.object(plaid_routes, "get_plaid_repo", return_value=fake_repo):
        result = await plaid_routes.delete_item("i1", request, purge=False)

    fake_repo.delete_item.assert_awaited_once_with("i1")
    fake_repo.purge_item.assert_not_called()
    assert result == {"message": "Bank connection removed"}


@pytest.mark.asyncio
async def test_delete_item_route_purge_true_calls_purge_item():
    from web.plaid import routes as plaid_routes

    fake_repo = MagicMock()
    fake_repo.get_item = AsyncMock(return_value={"item_id": "i1", "user_id": 7})
    fake_repo.delete_item = AsyncMock()
    fake_repo.purge_item = AsyncMock(
        return_value={
            "transactions_deleted": 10,
            "accounts_deleted": 2,
            "recurring_streams_deleted": 1,
            "plaid_items_deleted": 1,
        }
    )

    request = MagicMock()
    request.state.user = {"id": 7, "is_owner": False}

    with patch.object(plaid_routes, "get_plaid_repo", return_value=fake_repo):
        result = await plaid_routes.delete_item("i1", request, purge=True)

    fake_repo.purge_item.assert_awaited_once_with("i1")
    fake_repo.delete_item.assert_not_called()
    assert result["transactions_deleted"] == 10
    assert result["accounts_deleted"] == 2
    assert result["plaid_items_deleted"] == 1


@pytest.mark.asyncio
async def test_delete_item_route_rejects_non_owner():
    from fastapi import HTTPException

    from web.plaid import routes as plaid_routes

    fake_repo = MagicMock()
    fake_repo.get_item = AsyncMock(return_value={"item_id": "i1", "user_id": 99})
    fake_repo.delete_item = AsyncMock()
    fake_repo.purge_item = AsyncMock()

    request = MagicMock()
    request.state.user = {"id": 7, "is_owner": False}

    with patch.object(plaid_routes, "get_plaid_repo", return_value=fake_repo):
        with pytest.raises(HTTPException) as excinfo:
            await plaid_routes.delete_item("i1", request, purge=True)

    assert excinfo.value.status_code == 403
    fake_repo.purge_item.assert_not_called()
    fake_repo.delete_item.assert_not_called()
