"""
Regression tests for merchant-rule matching fallback onto
``transactions.display_title`` when Plaid does not supply a merchant.

The SQL is asserted at the fragment level (so the test exercises the exact
COALESCE that ships to production) and the repo paths are exercised with a
mocked asyncpg pool.
"""
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.merchant_rules.apply import _merchant_sql_params, preview_match_count
from web.merchant_rules.repo import MerchantRulesRepository


def test_name_kind_sql_has_display_title_fallback():
    sql, params = _merchant_sql_params("name", "pmts sec: ind")
    assert "COALESCE(NULLIF(t.merchant_name, ''), t.display_title, '')" in sql
    assert params[1] == "pmts sec: ind"


def test_eid_kind_sql_does_not_use_display_title():
    sql, _ = _merchant_sql_params("eid", "abc-12")
    assert "display_title" not in sql
    assert "merchant_entity_id" in sql


@pytest.mark.asyncio
async def test_preview_match_count_uses_fallback_key():
    """Category-less preview should build a ``name:`` key from merchant_label
    when merchant_name is empty and return the count + samples."""
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetchval.return_value = 3
    conn.fetch.return_value = [{"mn": "Pmts Sec: Ind"}]

    with patch("web.merchant_rules.apply.get_pool", AsyncMock(return_value=pool)):
        out = await preview_match_count(None, "Pmts Sec: Ind")

    assert out["match_count"] == 3
    assert out["sample_merchant_names"] == ["Pmts Sec: Ind"]
    assert out["merchant_key"] == "name:pmts sec: ind"
    assert out["display_label"] == "pmts sec: ind"


@pytest.mark.asyncio
async def test_preview_match_count_rejects_empty_inputs():
    with pytest.raises(ValueError):
        await preview_match_count(None, None)
    with pytest.raises(ValueError):
        await preview_match_count("", "")


@pytest.mark.asyncio
async def test_lookup_category_uses_fallback_display():
    """When merchant_name is empty, lookup should still match a rule keyed on
    the normalized display_title."""
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetchrow.return_value = {"category_id": 42}

    repo = MerchantRulesRepository()
    with patch("web.merchant_rules.repo.get_pool", AsyncMock(return_value=pool)):
        cat = await repo.lookup_category(None, None, "Pmts Sec: Ind")

    assert cat == 42
    sent_key = conn.fetchrow.await_args.args[1]
    assert sent_key == "name:pmts sec: ind"


@pytest.mark.asyncio
async def test_lookup_category_noop_without_any_identifier():
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    repo = MerchantRulesRepository()
    with patch("web.merchant_rules.repo.get_pool", AsyncMock(return_value=pool)):
        cat = await repo.lookup_category(None, None, None)
    assert cat is None
    conn.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_upsert_rule_accepts_fallback_display():
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetchrow.side_effect = [
        {"id": 1, "merchant_key": "name:pmts sec: ind", "category_id": 7},
        {"name": "Transfers"},
    ]
    repo = MerchantRulesRepository()
    with patch("web.merchant_rules.repo.get_pool", AsyncMock(return_value=pool)):
        out = await repo.upsert_rule(None, None, 7, "Pmts Sec: Ind")
    assert out["merchant_key"] == "name:pmts sec: ind"
    assert out["category_name"] == "Transfers"
