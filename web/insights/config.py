"""Threshold loader for the Insights feed.

Thresholds live in ``app_settings.insights_config`` (JSONB). This module
reads them with defaults so every builder imports plain, typed
constants instead of poking at the settings table directly.

The loader is intentionally side-effect-free and best-effort: if the
settings row is missing or the JSON is malformed, defaults win and a
warning is logged.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from web.db import get_pool

logger = logging.getLogger(__name__)


DEFAULTS: Dict[str, Any] = {
    "price_change_pct_threshold": 0.10,
    "forecast_window_days": 14,
    "utilization_warn_threshold": 0.75,
    "utilization_info_threshold": 0.30,
    "category_trend_pct_threshold": 0.25,
    "missed_recurring_grace_days": 3,
    "budget_risk_ratio": 0.90,
    "duplicate_similarity_pct": 0.20,
    "duplicate_min_monthly_cents": 500,
    "cache_ttl_seconds": 300,
    "snooze_max_days": 90,
    "card_prune_days": 30,
}


@dataclass(frozen=True)
class InsightsConfig:
    price_change_pct_threshold: float
    forecast_window_days: int
    utilization_warn_threshold: float
    utilization_info_threshold: float
    category_trend_pct_threshold: float
    missed_recurring_grace_days: int
    budget_risk_ratio: float
    duplicate_similarity_pct: float
    duplicate_min_monthly_cents: int
    cache_ttl_seconds: int
    snooze_max_days: int
    card_prune_days: int

    @classmethod
    def from_mapping(cls, overrides: Optional[Dict[str, Any]]) -> "InsightsConfig":
        merged = dict(DEFAULTS)
        if isinstance(overrides, dict):
            for key, val in overrides.items():
                if key in merged:
                    merged[key] = val
        return cls(**merged)  # type: ignore[arg-type]


async def load_config() -> InsightsConfig:
    """Read ``app_settings.insights_config`` and return a typed config.

    Returns the defaults if:
    - the settings row is missing,
    - the column was not yet migrated (older deploys), or
    - the JSON blob is corrupt.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            raw = await conn.fetchval(
                "SELECT insights_config FROM app_settings WHERE id = 1"
            )
    except Exception as exc:
        logger.warning("insights config load failed, using defaults: %s", exc)
        return InsightsConfig.from_mapping(None)

    if raw is None:
        return InsightsConfig.from_mapping(None)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("insights_config not JSON: %s", exc)
            return InsightsConfig.from_mapping(None)
    if not isinstance(raw, dict):
        return InsightsConfig.from_mapping(None)
    return InsightsConfig.from_mapping(raw)
