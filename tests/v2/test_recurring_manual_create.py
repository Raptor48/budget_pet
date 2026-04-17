"""Manual recurring stream creation (synthetic plaid_stream_id, stream_source=manual)."""
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.recurring.repo import RecurringRepository


@pytest.mark.asyncio
async def test_create_manual_stream_inserts():
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetchrow.return_value = {
        "id": 99,
        "plaid_stream_id": "manual:00000000-0000-0000-0000-000000000001",
        "account_id": 5,
        "direction": "outflow",
        "description": "Rent",
        "merchant_name": None,
        "frequency": "MONTHLY",
        "average_amount_cents": 150000,
        "last_amount_cents": 150000,
        "currency": "USD",
        "pfc_primary": None,
        "pfc_detailed": None,
        "first_date": None,
        "last_date": None,
        "is_active": True,
        "status": "MANUAL",
        "category_id": None,
        "user_label": None,
        "price_change_pct": None,
        "last_synced_at": None,
        "stream_source": "manual",
    }

    acc_inst = AsyncMock()
    acc_inst.get_account = AsyncMock(return_value={"id": 5, "user_id": 1})

    with patch("web.recurring.repo.get_pool", AsyncMock(return_value=pool)):
        with patch("web.recurring.repo.AccountsRepository", return_value=acc_inst):
            row = await RecurringRepository().create_manual_stream(
                1,
                {
                    "account_id": 5,
                    "direction": "outflow",
                    "description": "Rent",
                    "frequency": "MONTHLY",
                    "average_amount_cents": 150000,
                },
            )

    assert row["stream_source"] == "manual"
    assert row["plaid_stream_id"].startswith("manual:")
    args = conn.fetchrow.call_args[0]
    assert "manual" in args[0].lower()
