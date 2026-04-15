"""
Tests for Plaid sync logic: modified and removed transaction handling.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_txn(transaction_id: str, amount: float, category: list = None, pending: bool = False,
              merchant: str = "Merchant") -> dict:
    """Build a minimal Plaid transaction dict."""
    return {
        "transaction_id": transaction_id,
        "amount": amount,
        "date": "2024-01-15",
        "merchant_name": merchant,
        "name": merchant,
        "category": category or ["Food and Drink"],
        "personal_finance_category": {"detailed": "FOOD_AND_DRINK_RESTAURANTS", "primary": "FOOD_AND_DRINK"},
        "pending": pending,
        "account_id": "acct_001",
    }


def _make_removed(transaction_id: str) -> dict:
    return {"transaction_id": transaction_id}


# ---------------------------------------------------------------------------
# PlaidRepository.remove_transactions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_transactions_deletes_from_expenses_and_income():
    conn = AsyncMock()
    conn.execute = AsyncMock(side_effect=["DELETE 1", "DELETE 0"])

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_async_ctx(conn))

    from web.plaid.repo import PlaidRepository
    repo = PlaidRepository(pool)

    removed = [_make_removed("txn_001")]
    deleted = await repo.remove_transactions(removed)

    assert deleted == 1
    assert conn.execute.call_count == 2
    call_args = conn.execute.call_args_list
    assert "expenses" in call_args[0][0][0]
    assert "finance_income" in call_args[1][0][0]


@pytest.mark.asyncio
async def test_remove_transactions_empty_list():
    pool = MagicMock()
    from web.plaid.repo import PlaidRepository
    repo = PlaidRepository(pool)

    deleted = await repo.remove_transactions([])
    assert deleted == 0
    pool.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_remove_transactions_skips_entries_without_id():
    pool = MagicMock()
    from web.plaid.repo import PlaidRepository
    repo = PlaidRepository(pool)

    removed = [{"transaction_id": ""}, {}]
    deleted = await repo.remove_transactions(removed)
    assert deleted == 0


# ---------------------------------------------------------------------------
# PlaidRepository.import_transactions — modified (upsert updates fields)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_transactions_modified_updates_pending_status():
    """Modified transaction (pending → settled) should update is_pending in DB."""
    conn = AsyncMock()
    conn.executemany = AsyncMock()
    conn.execute = AsyncMock()

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_async_ctx(conn))

    from web.plaid.repo import PlaidRepository
    repo = PlaidRepository(pool)

    modified = [_make_txn("txn_pending_001", amount=50.0, pending=False)]
    category_map = {"Food and Drink": "Еда"}

    count = await repo.import_transactions(modified, category_map)

    assert count == 1
    sql_call = conn.execute.call_args[0][0]
    assert "ON CONFLICT" in sql_call
    assert "is_pending" in sql_call


# ---------------------------------------------------------------------------
# sync_all_items — integration: modified and removed are processed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_all_items_processes_modified_and_removed():
    """sync_all_items must call import_transactions for modified and remove_transactions for removed."""
    mock_repo = AsyncMock()
    mock_repo.get_all_items_with_tokens = AsyncMock(return_value=[{
        "item_id": "item_001",
        "access_token": "access-sandbox-token",
        "cursor": "cursor_v1",
    }])
    mock_repo.get_category_map = AsyncMock(return_value={"Food and Drink": "Еда"})
    mock_repo.import_transactions = AsyncMock(return_value=1)
    mock_repo.import_income = AsyncMock(return_value=0)
    mock_repo.remove_transactions = AsyncMock(return_value=1)
    mock_repo.update_cursor = AsyncMock()
    mock_repo.sync_balances = AsyncMock(return_value=0)
    mock_repo.sync_liabilities = AsyncMock()
    mock_repo.log_sync = AsyncMock()

    added = [_make_txn("txn_new", amount=25.0)]
    modified = [_make_txn("txn_old", amount=30.0, pending=False)]
    removed = [_make_removed("txn_gone")]

    # scheduler imports lazily from .repo and .client — patch at source
    with patch("web.plaid.repo.get_plaid_repo", return_value=mock_repo), \
         patch("web.plaid.client.get_transactions_sync", return_value={
             "added": added,
             "modified": modified,
             "removed": removed,
             "next_cursor": "cursor_v2",
         }), \
         patch("web.plaid.client.get_account_balances", return_value=[]), \
         patch("web.plaid.client.get_liabilities", return_value={"credit": [], "student": [], "mortgage": []}):

        from web.plaid.scheduler import sync_all_items
        results = await sync_all_items()

    assert len(results) == 1
    result = results[0]
    assert result["status"] == "ok"

    # import_transactions called twice: once for added, once for modified
    assert mock_repo.import_transactions.call_count == 2
    mock_repo.import_transactions.assert_any_call(added, {"Food and Drink": "Еда"})
    mock_repo.import_transactions.assert_any_call(modified, {"Food and Drink": "Еда"})

    # remove_transactions called with removed list
    mock_repo.remove_transactions.assert_called_once_with(removed)

    # cursor updated with new value
    mock_repo.update_cursor.assert_called_once_with("item_001", "cursor_v2")


@pytest.mark.asyncio
async def test_sync_all_items_skips_modified_when_empty():
    """When modified list is empty, import_transactions is called only once (for added)."""
    mock_repo = AsyncMock()
    mock_repo.get_all_items_with_tokens = AsyncMock(return_value=[{
        "item_id": "item_001",
        "access_token": "token",
        "cursor": None,
    }])
    mock_repo.get_category_map = AsyncMock(return_value={})
    mock_repo.import_transactions = AsyncMock(return_value=0)
    mock_repo.import_income = AsyncMock(return_value=0)
    mock_repo.remove_transactions = AsyncMock(return_value=0)
    mock_repo.update_cursor = AsyncMock()
    mock_repo.sync_balances = AsyncMock(return_value=0)
    mock_repo.sync_liabilities = AsyncMock()
    mock_repo.log_sync = AsyncMock()

    with patch("web.plaid.repo.get_plaid_repo", return_value=mock_repo), \
         patch("web.plaid.client.get_transactions_sync", return_value={
             "added": [], "modified": [], "removed": [], "next_cursor": "c1",
         }), \
         patch("web.plaid.client.get_account_balances", return_value=[]), \
         patch("web.plaid.client.get_liabilities", return_value={"credit": [], "student": [], "mortgage": []}):

        from web.plaid.scheduler import sync_all_items
        await sync_all_items()

    assert mock_repo.import_transactions.call_count == 1
    mock_repo.remove_transactions.assert_not_called()


# ---------------------------------------------------------------------------
# Async context manager helper
# ---------------------------------------------------------------------------

class _async_ctx:
    """Minimal async context manager that returns the given connection."""
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass
