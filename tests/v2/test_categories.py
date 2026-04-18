"""Tests for web/categories/repo.py"""
from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.categories.repo import CategoriesRepository, _pretty_name


class TestPrettyName:
    def test_basic_conversion(self):
        assert _pretty_name("FOOD_AND_DRINK_RESTAURANTS", "FOOD_AND_DRINK") == "Food & Drink: Restaurants"

    def test_no_primary(self):
        name = _pretty_name("ENTERTAINMENT_MUSIC_AND_AUDIO", None)
        assert name

    def test_primary_only(self):
        name = _pretty_name("TRANSPORTATION", "TRANSPORTATION")
        assert name

    def test_income(self):
        name = _pretty_name("INCOME_WAGES", "INCOME")
        assert "Income" in name or "Wages" in name


class TestCategoriesRepository:
    @pytest.fixture
    def repo(self):
        return CategoriesRepository()

    @pytest.mark.asyncio
    async def test_resolve_category_creates_new(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        # Sequence: primary lookup → primary insert (returns id) → detailed
        #           lookup → detailed insert (returns id).
        conn.fetchrow.side_effect = [
            None,          # _ensure_primary_category_id: no existing primary row
            {"id": 9},     # primary row inserted
            None,          # no match by pfc_detailed
            {"id": 42},    # detailed row inserted
        ]

        with patch("web.categories.repo.get_pool", AsyncMock(return_value=pool)):
            cid = await repo.resolve_category(
                pfc_detailed="FOOD_AND_DRINK_RESTAURANTS",
                pfc_primary="FOOD_AND_DRINK",
                pfc_icon_url="https://plaid.com/icon.png",
            )

        assert cid == 42

    @pytest.mark.asyncio
    async def test_resolve_category_existing(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.side_effect = [
            {"id": 9},                  # existing primary parent row
            {"id": 7, "parent_id": 9},  # existing detailed row, already linked
        ]

        with patch("web.categories.repo.get_pool", AsyncMock(return_value=pool)):
            cid = await repo.resolve_category(
                pfc_detailed="FOOD_AND_DRINK_RESTAURANTS",
                pfc_primary="FOOD_AND_DRINK",
            )

        assert cid == 7

    @pytest.mark.asyncio
    async def test_resolve_primary_only_returns_parent(self, repo):
        """When only `pfc_primary` is provided, the parent id is returned directly."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.side_effect = [
            {"id": 11},  # existing primary row
        ]

        with patch("web.categories.repo.get_pool", AsyncMock(return_value=pool)):
            cid = await repo.resolve_category(
                pfc_detailed=None,
                pfc_primary="TRANSPORTATION",
            )

        assert cid == 11

    @pytest.mark.asyncio
    async def test_resolve_relinks_orphan_detailed(self, repo):
        """A detailed row with stale parent_id gets updated to the correct parent."""
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow.side_effect = [
            {"id": 9},                      # ensure primary row
            {"id": 7, "parent_id": None},   # detailed row without a parent
        ]

        with patch("web.categories.repo.get_pool", AsyncMock(return_value=pool)):
            cid = await repo.resolve_category(
                pfc_detailed="FOOD_AND_DRINK_RESTAURANTS",
                pfc_primary="FOOD_AND_DRINK",
            )

        assert cid == 7
        # parent_id relink happens via conn.execute(UPDATE ...)
        conn.execute.assert_any_call(
            "UPDATE categories SET parent_id = $2 WHERE id = $1",
            7,
            9,
        )

    @pytest.mark.asyncio
    async def test_resolve_none_when_no_pfc(self, repo):
        result = await repo.resolve_category(None, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_category_rejects_plaid_pfc(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow = AsyncMock(return_value={"source": "plaid_pfc"})

        with patch("web.categories.repo.get_pool", AsyncMock(return_value=pool)):
            ok = await repo.delete_category(99)

        assert ok is False
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_category_allows_custom(self, repo):
        conn = AsyncMock()
        pool = make_mock_pool(conn)
        conn.fetchrow = AsyncMock(return_value={"source": "custom"})
        conn.execute = AsyncMock(return_value="DELETE 1")

        with patch("web.categories.repo.get_pool", AsyncMock(return_value=pool)):
            ok = await repo.delete_category(3)

        assert ok is True
        conn.execute.assert_called_once()
