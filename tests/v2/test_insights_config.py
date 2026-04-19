"""Tests for web/insights/config.py — threshold overrides from app_settings."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from tests.v2.conftest import make_mock_pool
from web.insights import config as insights_config
from web.insights.config import DEFAULTS, InsightsConfig, load_config


def test_from_mapping_defaults_when_none():
    cfg = InsightsConfig.from_mapping(None)
    assert cfg.price_change_pct_threshold == DEFAULTS["price_change_pct_threshold"]
    assert cfg.cache_ttl_seconds == DEFAULTS["cache_ttl_seconds"]


def test_from_mapping_overrides_known_keys():
    cfg = InsightsConfig.from_mapping(
        {
            "price_change_pct_threshold": 0.25,
            "cache_ttl_seconds": 60,
            "unknown_key_should_be_ignored": "sure",
        }
    )
    assert cfg.price_change_pct_threshold == 0.25
    assert cfg.cache_ttl_seconds == 60
    # Unaffected defaults remain.
    assert cfg.utilization_warn_threshold == DEFAULTS["utilization_warn_threshold"]


@pytest.mark.asyncio
async def test_load_config_reads_from_app_settings(monkeypatch):
    stored = {"cache_ttl_seconds": 12, "budget_risk_ratio": 0.5}
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=stored)
    pool = make_mock_pool(conn)

    async def _get_pool():
        return pool

    monkeypatch.setattr("web.insights.config.get_pool", _get_pool)

    cfg = await load_config()
    assert cfg.cache_ttl_seconds == 12
    assert cfg.budget_risk_ratio == 0.5


@pytest.mark.asyncio
async def test_load_config_handles_text_json(monkeypatch):
    stored_str = json.dumps({"snooze_max_days": 7})
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=stored_str)
    pool = make_mock_pool(conn)

    async def _get_pool():
        return pool

    monkeypatch.setattr("web.insights.config.get_pool", _get_pool)

    cfg = await load_config()
    assert cfg.snooze_max_days == 7


@pytest.mark.asyncio
async def test_load_config_returns_defaults_on_error(monkeypatch):
    async def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("web.insights.config.get_pool", _boom)

    cfg = await load_config()
    assert cfg.cache_ttl_seconds == DEFAULTS["cache_ttl_seconds"]
