"""
Transactions date-range helper used by the shared month/year picker.

Verifies:
  - get_date_range() builds SQL with the same privacy / ownership / sandbox
    filters as list_transactions, so picker bounds match what the user can see.
  - the route returns formatted min_month / max_month (YYYY-MM) and respects
    reports_include_plaid_sandbox().
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.transactions.repo import TransactionsRepository


@pytest.mark.asyncio
async def test_get_date_range_returns_earliest_and_latest():
    repo = TransactionsRepository()
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetchrow.return_value = {"earliest": date(2024, 5, 3), "latest": date(2026, 4, 16)}
    with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
        result = await repo.get_date_range(user_id=1, viewer_user_id=1)
    assert result == {"earliest": date(2024, 5, 3), "latest": date(2026, 4, 16)}


@pytest.mark.asyncio
async def test_get_date_range_no_transactions_returns_nulls():
    repo = TransactionsRepository()
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetchrow.return_value = {"earliest": None, "latest": None}
    with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
        result = await repo.get_date_range()
    assert result == {"earliest": None, "latest": None}


@pytest.mark.asyncio
async def test_get_date_range_applies_filters_in_sql():
    """
    SQL must include the account-owner filter, sandbox exclusion and private-row
    visibility check so the picker never shows months the caller cannot see.
    """
    repo = TransactionsRepository()
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    captured = {}

    async def fetchrow(sql, *args):
        captured["sql"] = sql
        captured["args"] = args
        return {"earliest": date(2025, 1, 1), "latest": date(2026, 1, 1)}

    conn.fetchrow = AsyncMock(side_effect=fetchrow)

    with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
        await repo.get_date_range(user_id=7, viewer_user_id=7, exclude_plaid_sandbox=True)

    sql = captured["sql"]
    assert "a.user_id = $1" in sql
    assert "plaid_sandbox" in sql
    assert "NOT t.is_private" in sql
    assert captured["args"] == (7, 7)


@pytest.mark.asyncio
async def test_get_date_range_no_viewer_skips_privacy_filter():
    repo = TransactionsRepository()
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    captured = {}

    async def fetchrow(sql, *args):
        captured["sql"] = sql
        captured["args"] = args
        return {"earliest": None, "latest": None}

    conn.fetchrow = AsyncMock(side_effect=fetchrow)

    with patch("web.transactions.repo.get_pool", AsyncMock(return_value=pool)):
        await repo.get_date_range()

    assert "NOT t.is_private" not in captured["sql"]
    assert captured["args"] == ()


@pytest.mark.asyncio
async def test_date_range_route_formats_yyyy_mm():
    """The HTTP route renders YYYY-MM strings and preserves raw dates."""
    from web.transactions.routes import get_transactions_date_range

    fake_request = MagicMock()
    fake_request.state.user = {"id": 1, "is_owner": True}

    fake_repo = MagicMock()
    fake_repo.get_date_range = AsyncMock(
        return_value={"earliest": date(2024, 5, 3), "latest": date(2026, 4, 16)}
    )

    with patch("web.transactions.routes._repo", return_value=fake_repo), patch(
        "web.transactions.routes.reports_include_plaid_sandbox", return_value=True
    ):
        response = await get_transactions_date_range(fake_request)

    assert response.min_month == "2024-05"
    assert response.max_month == "2026-04"
    assert response.earliest == date(2024, 5, 3)
    assert response.latest == date(2026, 4, 16)

    fake_repo.get_date_range.assert_awaited_once()
    kwargs = fake_repo.get_date_range.call_args.kwargs
    # Owner sees everyone's data → user_id filter stays None.
    assert kwargs.get("user_id") is None
    assert kwargs.get("viewer_user_id") == 1
    assert kwargs.get("exclude_plaid_sandbox") is False


@pytest.mark.asyncio
async def test_date_range_route_empty_returns_nulls():
    from web.transactions.routes import get_transactions_date_range

    fake_request = MagicMock()
    fake_request.state.user = {"id": 5, "is_owner": False}

    fake_repo = MagicMock()
    fake_repo.get_date_range = AsyncMock(
        return_value={"earliest": None, "latest": None}
    )

    with patch("web.transactions.routes._repo", return_value=fake_repo), patch(
        "web.transactions.routes.reports_include_plaid_sandbox", return_value=False
    ):
        response = await get_transactions_date_range(fake_request)

    assert response.min_month is None
    assert response.max_month is None
    kwargs = fake_repo.get_date_range.call_args.kwargs
    # Same family-wide range as owners; hidden rows use viewer_user_id in SQL.
    assert kwargs.get("user_id") is None
    assert kwargs.get("viewer_user_id") == 5
    assert kwargs.get("exclude_plaid_sandbox") is True


@pytest.mark.asyncio
async def test_list_transactions_route_family_wide_for_non_owner():
    """Members must not have user_id forced to self — list is family-wide + privacy."""
    from web.transactions.routes import list_transactions

    fake_request = MagicMock()
    fake_request.state.user = {"id": 5, "is_owner": False}

    fake_repo = MagicMock()
    fake_repo.list_transactions = AsyncMock(return_value=[])

    with patch("web.transactions.routes._repo", return_value=fake_repo), patch(
        "web.transactions.routes.reports_include_plaid_sandbox", return_value=True
    ), patch("web.transactions.routes._enrich_many", new_callable=AsyncMock, return_value=[]):
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
            limit=200,
            offset=0,
        )

    kwargs = fake_repo.list_transactions.call_args.kwargs
    assert kwargs.get("user_id") is None
    assert kwargs.get("viewer_user_id") == 5
