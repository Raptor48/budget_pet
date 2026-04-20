"""
Plaid personal-finance category (PFC) → human-readable labels.

Single source of truth for display strings built from ``pfc_detailed`` /
``pfc_primary`` enums. Used by ``CategoriesRepository`` when auto-creating
rows and by ``RecurringRepository.list_streams`` when no resolved category
name exists from JOINs.
"""
from __future__ import annotations

from typing import Dict, Optional

# Human-readable labels for PFC primary enum values (mirrors categories/repo).
PFC_PRIMARY_LABELS: Dict[str, str] = {
    "INCOME": "Income",
    "TRANSFER_IN": "Transfer In",
    "TRANSFER_OUT": "Transfer Out",
    "LOAN_PAYMENTS": "Loan Payments",
    "BANK_FEES": "Bank Fees",
    "ENTERTAINMENT": "Entertainment",
    "FOOD_AND_DRINK": "Food & Drink",
    "GENERAL_MERCHANDISE": "Shopping",
    "HOME_IMPROVEMENT": "Home Improvement",
    "MEDICAL": "Medical",
    "PERSONAL_CARE": "Personal Care",
    "GENERAL_SERVICES": "Services",
    "GOVERNMENT_AND_NON_PROFIT": "Government & Non-Profit",
    "TRANSPORTATION": "Transportation",
    "TRAVEL": "Travel",
    "RENT_AND_UTILITIES": "Rent & Utilities",
}


def format_pfc_detailed_label(pfc_detailed: str, pfc_primary: Optional[str] = None) -> str:
    """Convert FOOD_AND_DRINK_RESTAURANTS → Food & Drink: Restaurants."""
    primary_label = PFC_PRIMARY_LABELS.get(pfc_primary or "", pfc_primary or "")
    # Strip primary prefix from detailed if present
    if pfc_primary and pfc_detailed.startswith(pfc_primary + "_"):
        suffix = pfc_detailed[len(pfc_primary) + 1 :]
    else:
        suffix = pfc_detailed
    suffix = suffix.replace("_", " ").title()
    if primary_label and suffix and suffix.upper() != pfc_primary:
        return f"{primary_label}: {suffix}"
    return suffix or primary_label


def format_plaid_category_for_display(
    pfc_detailed: Optional[str],
    pfc_primary: Optional[str],
) -> Optional[str]:
    """Best human label from PFC fields when no DB ``category.name`` is available."""
    d = (pfc_detailed or "").strip()
    p = (pfc_primary or "").strip()
    if d:
        return format_pfc_detailed_label(d, p or None)
    if p:
        return PFC_PRIMARY_LABELS.get(p, format_pfc_detailed_label(p, p))
    return None


__all__ = [
    "PFC_PRIMARY_LABELS",
    "format_pfc_detailed_label",
    "format_plaid_category_for_display",
]
