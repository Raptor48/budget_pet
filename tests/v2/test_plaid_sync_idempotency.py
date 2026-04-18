"""
Sync idempotency: re-importing the same Plaid transactions is a no-op at the row
level thanks to ``ON CONFLICT (plaid_transaction_id) DO UPDATE``. This protects
us when the cursor is advanced after a successful import but the scheduler is
re-run against the same cursor (e.g. manual Sync → automatic Sync).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.plaid.repo import PlaidRepository


def _make_txn(txn_id: str, account_id: str):
    txn = MagicMock()
    txn.to_dict.return_value = {
        "transaction_id": txn_id,
        "account_id": account_id,
        "amount": 10.0,
        "iso_currency_code": "USD",
        "date": "2026-04-15",
        "authorized_date": None,
        "datetime": None,
        "authorized_datetime": None,
        "name": "Test",
        "merchant_name": "Test",
        "merchant_entity_id": None,
        "logo_url": None,
        "website": None,
        "payment_channel": "online",
        "personal_finance_category": {
            "primary": "FOOD_AND_DRINK",
            "detailed": "FOOD_AND_DRINK_COFFEE",
            "confidence_level": "HIGH",
        },
        "personal_finance_category_icon_url": None,
        "counterparties": [],
        "location": None,
        "payment_meta": None,
        "pending": False,
    }
    return txn


@pytest.mark.asyncio
async def test_import_uses_on_conflict_upsert_sql():
    """The insert statement must rely on ON CONFLICT for idempotency."""
    repo = PlaidRepository()
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    executed: list[str] = []

    async def execute(sql, *args):
        executed.append(sql)
        return "INSERT 0 1"

    conn.execute = AsyncMock(side_effect=execute)

    txns = [_make_txn("txn-1", "acct-1")]
    with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)), patch(
        "web.merchant_rules.repo.MerchantRulesRepository.lookup_category",
        new_callable=AsyncMock,
        return_value=None,
    ):
        count = await repo.import_transactions(txns, {"acct-1": 1}, source="plaid")

    assert count == 1
    assert any("ON CONFLICT (plaid_transaction_id)" in sql for sql in executed), (
        "import_transactions must upsert, not plain INSERT"
    )
    assert any("COALESCE(transactions.category_id, EXCLUDED.category_id)" in sql for sql in executed), (
        "user-set category must be preserved on re-import"
    )


@pytest.mark.asyncio
async def test_double_import_same_transactions_no_new_rows():
    """
    Simulate an at-least-once sync: the same list of Plaid transactions is
    imported twice (e.g. cursor not yet persisted on the first try, or a
    background retry). Both runs must report the same logical count and the
    second run must not insert duplicates — the DB-level ON CONFLICT guarantees
    this, here we simply assert both runs complete without raising and both
    INSERTs use the upsert clause.
    """
    repo = PlaidRepository()
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    executed: list[str] = []

    async def execute(sql, *args):
        executed.append(sql)
        return "INSERT 0 1"

    conn.execute = AsyncMock(side_effect=execute)

    txns = [_make_txn("txn-a", "acct-1"), _make_txn("txn-b", "acct-1")]

    with patch("web.plaid.repo.get_pool", AsyncMock(return_value=pool)), patch(
        "web.merchant_rules.repo.MerchantRulesRepository.lookup_category",
        new_callable=AsyncMock,
        return_value=None,
    ):
        first = await repo.import_transactions(txns, {"acct-1": 1}, source="plaid")
        second = await repo.import_transactions(txns, {"acct-1": 1}, source="plaid")

    assert first == 2
    assert second == 2
    # Every INSERT issued by both runs must be an upsert, so replaying is safe.
    insert_statements = [sql for sql in executed if "INSERT INTO transactions" in sql]
    assert len(insert_statements) == 4
    assert all("ON CONFLICT (plaid_transaction_id)" in sql for sql in insert_statements)


@pytest.mark.asyncio
async def test_cursor_not_advanced_if_import_fails():
    """
    Scheduler contract: if ``import_transactions`` raises, the cursor must NOT
    be advanced so the next run re-fetches the same page from Plaid and the
    upsert semantics handle it idempotently. This is the critical boundary for
    at-least-once correctness.
    """
    from web.plaid import scheduler

    mock_repo = AsyncMock()
    mock_repo.get_items.return_value = [
        {"item_id": "item-1", "access_token": "token-1", "cursor": "cur-0", "user_id": 1},
    ]
    mock_repo.build_account_id_map = AsyncMock(return_value={"acct-1": 1})
    mock_repo.import_transactions = AsyncMock(side_effect=RuntimeError("db down"))
    mock_repo.delete_removed_transactions = AsyncMock(return_value=0)
    mock_repo.update_cursor = AsyncMock()
    mock_repo.log_sync = AsyncMock()

    with patch("web.plaid.repo.get_plaid_repo", return_value=mock_repo), \
         patch(
             "web.plaid.client.get_transactions_sync",
             return_value={
                 "added": [_make_txn("txn-1", "acct-1")],
                 "modified": [],
                 "removed": [],
                 "next_cursor": "cur-1",
                 "has_more": False,
             },
         ), \
         patch("web.plaid.client.get_account_balances", return_value=[]), \
         patch(
             "web.accounts.repo.AccountsRepository.provision_from_plaid",
             AsyncMock(return_value=0),
         ), \
         patch(
             "web.categories.repo.CategoriesRepository.resolve_category",
             AsyncMock(return_value=1),
         ):
        results = await scheduler.sync_all_items()

    assert len(results) == 1
    assert results[0]["status"] == "error"
    # This is the whole point of the test — a DB failure must never leave the
    # cursor advanced past rows we haven't persisted.
    mock_repo.update_cursor.assert_not_called()
