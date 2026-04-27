"""
Tests for the ``description_contains`` filter on merchant_category_rules.

Three layers:

1. SQL-shape: ``_merchant_sql_params`` injects the substring AND clause
   only when a non-blank filter is passed, lowercases on the way in,
   and never uses a positional placeholder collision when the base
   ``name`` / ``eid`` clauses already consumed positions $1 / $2.
2. Repo: ``upsert_rule`` writes the lower-cased filter, ``lookup_category``
   sends the haystack as $2 and orders so non-NULL filters win, and
   blank inputs are normalized to ``NULL``.
3. Preview: ``preview_match_count`` returns the new
   ``distinct_description_count`` field so the UI can decide whether
   to surface the "narrow with description" affordance.
"""
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.merchant_rules.apply import _merchant_sql_params, preview_match_count
from web.merchant_rules.repo import MerchantRulesRepository, _normalize_filter


# ---------------------------------------------------------------------------
# _normalize_filter
# ---------------------------------------------------------------------------


def test_normalize_filter_lowercases_and_strips():
    assert _normalize_filter("  ALLA  ") == "alla"


def test_normalize_filter_blank_to_none():
    assert _normalize_filter(None) is None
    assert _normalize_filter("") is None
    assert _normalize_filter("   ") is None


# ---------------------------------------------------------------------------
# SQL fragment shape
# ---------------------------------------------------------------------------


def test_sql_no_filter_omits_position_clause():
    sql, params = _merchant_sql_params("name", "zelle")
    assert "position(" not in sql
    assert params == [["plaid", "plaid_sandbox"], "zelle"]


def test_sql_with_filter_appends_position_clause_and_param():
    sql, params = _merchant_sql_params("name", "zelle", description_contains="ALLA")
    # Filter is normalized (lower + trim) before going into the SQL params.
    assert params[-1] == "alla"
    # Two position() checks: one against name, one against display_title.
    assert sql.count("position($3 IN") == 2
    # The base WHERE must remain intact.
    assert "merchant_name" in sql
    assert "display_title" in sql


def test_sql_blank_filter_treated_as_no_filter():
    sql_no, params_no = _merchant_sql_params("eid", "abc-12")
    sql_blank, params_blank = _merchant_sql_params("eid", "abc-12", description_contains="   ")
    assert sql_no == sql_blank
    assert params_no == params_blank


def test_sql_eid_with_filter_uses_third_positional():
    """When the kind is ``eid`` (params $1, $2), the filter must land at $3."""
    sql, params = _merchant_sql_params("eid", "stable-id", description_contains="rent")
    assert "position($3 IN" in sql
    assert params == [["plaid", "plaid_sandbox"], "stable-id", "rent"]


# ---------------------------------------------------------------------------
# Repo behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_rule_writes_lowercased_filter():
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetchrow.side_effect = [
        {
            "id": 7,
            "merchant_key": "name:zelle",
            "category_id": 9,
            "description_contains": "alla",
        },
        {"name": "Rent"},
    ]
    repo = MerchantRulesRepository()
    with patch("web.merchant_rules.repo.get_pool", AsyncMock(return_value=pool)):
        out = await repo.upsert_rule(
            None, "Zelle", 9, description_contains=" ALLA "
        )
    # Filter is normalized on the way in.
    insert_args = conn.fetchrow.await_args_list[0].args
    assert insert_args[3] == "alla"
    assert out["description_contains"] == "alla"


@pytest.mark.asyncio
async def test_upsert_rule_blank_filter_persisted_as_null():
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetchrow.side_effect = [
        {
            "id": 8,
            "merchant_key": "name:zelle",
            "category_id": 9,
            "description_contains": None,
        },
        {"name": "Transfer Out"},
    ]
    repo = MerchantRulesRepository()
    with patch("web.merchant_rules.repo.get_pool", AsyncMock(return_value=pool)):
        out = await repo.upsert_rule(None, "Zelle", 9, description_contains="   ")
    insert_args = conn.fetchrow.await_args_list[0].args
    assert insert_args[3] is None
    assert out["description_contains"] is None


@pytest.mark.asyncio
async def test_lookup_category_passes_haystack_lowercased():
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetchrow.return_value = {"category_id": 42}
    repo = MerchantRulesRepository()
    with patch("web.merchant_rules.repo.get_pool", AsyncMock(return_value=pool)):
        await repo.lookup_category(
            None,
            "Zelle",
            description="Zelle Payment to ALLA 24800561672",
        )
    args = conn.fetchrow.await_args.args
    assert args[1] == "name:zelle"
    # Haystack is lowercased on the Python side so the SQL position()
    # comparison is a direct substring match.
    assert args[2] == "zelle payment to alla 24800561672"


@pytest.mark.asyncio
async def test_lookup_category_no_description_passes_empty_haystack():
    """Legacy callers that don't pass ``description`` still work — the
    SQL guard ``$2::text <> ''`` ensures the filter clause never fires
    against a blank haystack, so generic rules still match."""
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetchrow.return_value = {"category_id": 5}
    repo = MerchantRulesRepository()
    with patch("web.merchant_rules.repo.get_pool", AsyncMock(return_value=pool)):
        cat = await repo.lookup_category(None, "Zelle")
    assert cat == 5
    args = conn.fetchrow.await_args.args
    assert args[2] == ""


@pytest.mark.asyncio
async def test_lookup_category_sql_orders_specific_first():
    """The fetched rule comes from a SQL with ``ORDER BY description_contains
    IS NULL`` so the more specific row wins. This test asserts the SQL
    text shipped to asyncpg includes that clause — protects against an
    accidental refactor that drops it."""
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    conn.fetchrow.return_value = {"category_id": 1}
    repo = MerchantRulesRepository()
    with patch("web.merchant_rules.repo.get_pool", AsyncMock(return_value=pool)):
        await repo.lookup_category(None, "Zelle", description="…alla…")
    sent_sql = conn.fetchrow.await_args.args[0]
    assert "ORDER BY description_contains IS NULL" in sent_sql
    assert "LIMIT 1" in sent_sql


# ---------------------------------------------------------------------------
# Preview match count surfaces distinct_description_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_match_count_returns_distinct_description_count():
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    # Two fetchval calls in order: filtered-match-count, distinct-description-count
    conn.fetchval.side_effect = [12, 5]
    conn.fetch.return_value = [{"mn": "Zelle"}]

    with patch("web.merchant_rules.apply.get_pool", AsyncMock(return_value=pool)):
        out = await preview_match_count(None, "Zelle")

    assert out["match_count"] == 12
    assert out["distinct_description_count"] == 5


@pytest.mark.asyncio
async def test_preview_for_draft_returns_distinct_description_count():
    """Regression: the with-category preview path (the one the smart
    popover actually uses, since it always passes ``category_id``) must
    surface ``distinct_description_count`` so the UI can decide whether
    to render the "narrow with description" option.

    The first iteration shipped this field only via ``preview_match_count``
    — the FE was always calling ``preview_for_draft`` and saw ``None``,
    so the narrow option was hidden even on merchants with 476 distinct
    Zelle descriptions. This test guards against the regression."""
    from web.merchant_rules.apply import preview_for_draft

    conn = AsyncMock()
    pool = make_mock_pool(conn)
    # _preview_conn fires four fetchval calls in this order:
    # 1) eligible_count, 2) skipped_splits_count,
    # 3) skipped_custom_category_count, 4) distinct_description_count
    # Plus one more for skipped_has_entity_id (only for kind="name").
    conn.fetchval.side_effect = [120, 0, 0, 0, 47]
    conn.fetch.return_value = [{"mn": "Zelle"}]

    with patch("web.merchant_rules.apply.get_pool", AsyncMock(return_value=pool)):
        out = await preview_for_draft(None, "Zelle", category_id=9)

    assert out["distinct_description_count"] == 47


@pytest.mark.asyncio
async def test_preview_match_count_with_filter_narrows_count():
    """When a filter is supplied the match_count reflects the filtered
    set, but distinct_description_count is unaffected (the UI uses it
    to decide whether the filter affordance is meaningful — that
    decision shouldn't depend on the current draft filter)."""
    conn = AsyncMock()
    pool = make_mock_pool(conn)
    # filtered count → 3; distinct descriptions ignoring the filter → 5
    conn.fetchval.side_effect = [3, 5]
    conn.fetch.return_value = [{"mn": "Zelle"}]

    with patch("web.merchant_rules.apply.get_pool", AsyncMock(return_value=pool)):
        out = await preview_match_count(
            None, "Zelle", description_contains="alla"
        )

    assert out["match_count"] == 3
    assert out["distinct_description_count"] == 5
