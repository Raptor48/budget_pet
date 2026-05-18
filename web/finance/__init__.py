"""
Cross-cutting finance helpers — predicates and SQL fragments shared between
``web.reports``, ``web.budgets``, ``web.transactions``, and ``web.bot_api``.

Everything in here is *read-only* SQL composition. The actual aggregation
queries live with their domain — but every place that filters by
``transaction_class``, ``is_private``, or ``source = 'plaid_sandbox'``
should source the predicate from this module so the family of views stays
in lockstep.
"""

from .predicates import (
    expense_predicate,
    income_predicate,
    internal_transfer_predicate,
    non_receivable_category_filter,
    not_internal_transfer_predicate,
    private_visibility_filter,
    sandbox_exclusion_filter,
)

__all__ = [
    "expense_predicate",
    "income_predicate",
    "internal_transfer_predicate",
    "non_receivable_category_filter",
    "not_internal_transfer_predicate",
    "private_visibility_filter",
    "sandbox_exclusion_filter",
]
