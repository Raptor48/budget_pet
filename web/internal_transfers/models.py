"""Pydantic models for the internal-transfers settings surface."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class InternalTransferSettings(BaseModel):
    """Family-wide list of counterparty names to auto-flag as internal transfers.

    Names are stored verbatim as the user typed them (useful for display);
    the classifier normalizes them to uppercase + strips bank boilerplate
    before matching. Exposing the raw values keeps the settings dialog
    honest — what you see is what you configured.
    """

    names: List[str] = Field(default_factory=list)


class InternalTransferSettingsUpdate(BaseModel):
    """Replace the full list on each save — simpler than incremental ops and
    matches how the UI renders/edits the entire list at once."""

    names: List[str] = Field(default_factory=list)


RescanHorizon = Literal["last_90_days", "all_time"]


class InternalTransferRescanRequest(BaseModel):
    """Re-run the classifier over historical transactions.

    Two modes keep the cost predictable: ``last_90_days`` matches the
    horizon used after a names-list save, while ``all_time`` is an explicit
    opt-in for retroactive cleanups. Manual user flags are never overridden
    regardless of the mode.
    """

    horizon: RescanHorizon = "last_90_days"


class InternalTransferRescanResult(BaseModel):
    """Outcome of a rescan pass.

    ``rows_updated`` is the total number of transactions whose
    ``is_internal_transfer`` flag flipped to TRUE in this pass, across both
    the name-matcher and the family-account pair-matcher. ``name_rows_updated``
    and ``pair_rows_updated`` break that total down by source so the UI
    can surface what actually changed. Some rows may be counted once in each
    stage if both classifiers agree (rare but possible); for the UI we
    treat them as independent, which keeps the message honest about how
    each stage contributed.
    """

    rows_updated: int
    name_rows_updated: int = 0
    pair_rows_updated: int = 0
    horizon: RescanHorizon
    configured_names_count: int


class InternalTransferSettingsOut(InternalTransferSettings):
    """Response shape — identical to the request + an echo field the UI
    uses to render the normalized form next to the raw value for debugging.
    Optional; the UI works fine without it."""

    normalized_names: Optional[List[str]] = None
