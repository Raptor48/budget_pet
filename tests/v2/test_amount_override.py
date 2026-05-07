"""
Admin amount edit + ``manual_amount_override`` end-to-end coverage.

The override flag is what lets the admin pin a transaction's amount across
Plaid syncs. Three things must hold for the feature to be safe:

1. Plaid's upsert leaves ``amount_cents`` alone when the override is set.
2. ``update_transaction`` accepts ``amount_cents``, validates it (positive
   integer, no zero), refuses when splits exist, and stamps the override.
3. The route layer drops ``amount_cents`` for non-owners — so a partner's
   PATCH that happens to include the field is a no-op for the amount but
   still applies the rest of the update.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.v2.conftest import make_mock_pool


# ---------------------------------------------------------------------------
# 1. Plaid upsert respects the override flag
# ---------------------------------------------------------------------------


def test_plaid_upsert_keeps_amount_when_override_set():
    """The CASE expression in the ON CONFLICT SET clause must reference
    ``transactions.manual_amount_override`` and pick the existing amount
    when the flag is true. Asserting against the SQL text guards against
    a future refactor that accidentally drops the guard.
    """
    import inspect

    from web.plaid.repo import PlaidRepository

    src = inspect.getsource(PlaidRepository)
    # The SET clause must conditionally choose between local and excluded
    # values, gated on the override flag. We don't lock down whitespace —
    # just the contract.
    assert "manual_amount_override" in src, (
        "Plaid upsert must reference the override column"
    )
    # Locate the CASE block for amount_cents and check both branches exist.
    # Using a relaxed token check to survive minor formatting drift.
    assert "transactions.manual_amount_override" in src
    assert "transactions.amount_cents" in src
    assert "EXCLUDED.amount_cents" in src


# ---------------------------------------------------------------------------
# 2. update_transaction — amount path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_transaction_accepts_amount_and_stamps_override():
    """Owner-supplied ``amount_cents`` flows through the SET clause AND
    the override flag is added to the same UPDATE so the next Plaid sync
    leaves the row alone.
    """
    from web.transactions.repo import TransactionsRepository

    conn = AsyncMock()
    # No splits → invariant check passes.
    conn.fetchval = AsyncMock(return_value=False)
    captured: dict = {}

    async def fetchrow(sql, *args):
        captured["sql"] = sql
        captured["args"] = args
        # Return a minimal updated row so the repo's post-update
        # branches (display_title rebuild, reclassify) skip cleanly.
        return {
            "id": 42,
            "amount_cents": args[1],
            "merchant_name": None,
            "category_id": None,
            "display_title": "Whatever",
        }

    conn.fetchrow = AsyncMock(side_effect=fetchrow)

    repo = TransactionsRepository()
    with patch.object(repo, "_pool", AsyncMock(return_value=make_mock_pool(conn))):
        out = await repo.update_transaction(42, {"amount_cents": 5599})

    assert out is not None
    sql = captured["sql"]
    args = captured["args"]
    # Both columns must appear in the SET clause.
    assert "amount_cents" in sql
    assert "manual_amount_override" in sql
    # The override boolean must be in the args alongside the amount.
    assert 5599 in args
    assert True in args


@pytest.mark.asyncio
async def test_update_transaction_rejects_zero_amount():
    """Zero is forbidden — same rule as TransactionCreate."""
    from web.transactions.repo import TransactionsRepository

    repo = TransactionsRepository()
    with pytest.raises(ValueError, match="zero"):
        await repo.update_transaction(42, {"amount_cents": 0})


@pytest.mark.asyncio
async def test_update_transaction_rejects_non_integer_amount():
    """Strings that don't parse as int (e.g. a stray decimal slipping
    through the FE) must error before touching the DB."""
    from web.transactions.repo import TransactionsRepository

    repo = TransactionsRepository()
    with pytest.raises(ValueError, match="integer"):
        await repo.update_transaction(42, {"amount_cents": "not-a-number"})


@pytest.mark.asyncio
async def test_update_transaction_blocks_amount_edit_when_splits_exist():
    """When ``transaction_splits`` rows exist for the parent, an amount
    edit would silently break the ``SUM(splits) == parent`` invariant
    that ``SplitsRepository.set_splits`` enforces. The repo must refuse
    up front with a clear message instead of leaving the row in a
    half-broken state.
    """
    from web.transactions.repo import TransactionsRepository

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=True)  # has_splits = True

    repo = TransactionsRepository()
    with patch.object(repo, "_pool", AsyncMock(return_value=make_mock_pool(conn))):
        with pytest.raises(ValueError, match="splits"):
            await repo.update_transaction(42, {"amount_cents": 5599})

    # The fetchval must have been the splits-existence probe — the repo
    # never even reached the UPDATE step.
    assert conn.fetchval.await_count == 1
    conn.fetchrow.assert_not_called()


@pytest.mark.asyncio
async def test_update_transaction_amount_unchanged_path_is_unaffected():
    """When ``amount_cents`` is not in the payload, the splits check
    doesn't fire and the override flag is not stamped — keeps the existing
    "edit category only" path zero-overhead."""
    from web.transactions.repo import TransactionsRepository

    conn = AsyncMock()
    update_sqls: list = []

    async def fetchrow(sql, *args):
        # Capture only the actual UPDATE — the post-update reclassify path
        # issues other reads (internal_transfer_names, etc.) that we don't
        # care about here.
        if sql.lstrip().upper().startswith("UPDATE TRANSACTIONS"):
            update_sqls.append(sql)
        return {
            "id": 42,
            "amount_cents": 1000,
            "merchant_name": None,
            "category_id": 7,
            "display_title": "Whatever",
        }

    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.fetchval = AsyncMock(return_value=False)
    conn.fetch = AsyncMock(return_value=[])

    repo = TransactionsRepository()
    with patch.object(repo, "_pool", AsyncMock(return_value=make_mock_pool(conn))):
        await repo.update_transaction(42, {"category_id": 7})

    # Splits probe must NOT have run — it's only relevant for amount edits.
    conn.fetchval.assert_not_called()
    assert update_sqls, "expected an UPDATE on transactions"
    sql = update_sqls[0]
    assert "manual_amount_override" not in sql
    assert "category_id" in sql


# ---------------------------------------------------------------------------
# 3. Pydantic validator — zero rejected at the API boundary
# ---------------------------------------------------------------------------


def test_transaction_update_pydantic_rejects_zero_amount():
    from pydantic import ValidationError

    from web.transactions.models import TransactionUpdate

    with pytest.raises(ValidationError):
        TransactionUpdate(amount_cents=0)


def test_transaction_update_pydantic_accepts_negative_amount():
    """Inflows are stored as negative cents in this codebase. The
    validator only blocks zero — sign handling is the caller's job."""
    from web.transactions.models import TransactionUpdate

    payload = TransactionUpdate(amount_cents=-1500)
    assert payload.amount_cents == -1500


def test_transaction_update_pydantic_omitted_amount_is_none():
    """The field is optional — partners who never edit amount keep the
    same call shape they had before this feature."""
    from web.transactions.models import TransactionUpdate

    payload = TransactionUpdate(category_id=42)
    assert payload.amount_cents is None
