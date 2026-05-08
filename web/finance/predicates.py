"""
Canonical SQL predicate fragments for the finance read paths.

The four-class classifier (``transaction_class``) and the privacy/sandbox
filters were duplicated by hand across ``web.reports.repo``,
``web.budgets.repo``, ``web.transactions.repo``, and ``web.bot_api.repo``.
That duplication produced two real bugs in the wild:

1. The bot leaderboard read raw ``t.date``/``COALESCE(transaction_class,
   'expense')`` while reports used ``COALESCE(authorized_date, date)`` and
   the canonical class predicate, so sandbox demos and post-by-one-day
   transactions disagreed between screens.
2. The privacy filter (``viewer_user_id``) had three slightly different
   string forms — same logic, different aliases — making refactors risky.

Centralising here lets every aggregator emit the same SQL. Helpers return
plain string fragments so they compose into the existing ``f"…"``-built
queries without dragging in a query builder. Keep the API tiny.

All helpers are pure: they never read env or DB. The sandbox helper
delegates to :func:`web.env_flags.reports_include_plaid_sandbox` for the
runtime toggle so callers don't need to import env_flags themselves.
"""
from __future__ import annotations

from web.env_flags import reports_include_plaid_sandbox


def _qualify(alias: str) -> str:
    """Return ``"alias."`` or empty string for no-alias use."""
    return f"{alias}." if alias else ""


# ---------------------------------------------------------------------------
# transaction_class predicates
# ---------------------------------------------------------------------------
def income_predicate(alias: str = "t") -> str:
    """``transaction_class = 'income'`` — canonical 'this row is income'."""
    return f"{_qualify(alias)}transaction_class = 'income'"


def expense_predicate(alias: str = "t") -> str:
    """``transaction_class = 'expense'`` — canonical 'this row is an expense'."""
    return f"{_qualify(alias)}transaction_class = 'expense'"


def internal_transfer_predicate(alias: str = "t") -> str:
    """``transaction_class = 'internal_transfer'`` — moves between own accounts."""
    return f"{_qualify(alias)}transaction_class = 'internal_transfer'"


def not_internal_transfer_predicate(alias: str = "t") -> str:
    """``transaction_class <> 'internal_transfer'`` — kept for legacy callsites
    that haven't switched to the affirmative ``income/expense`` predicates."""
    return f"{_qualify(alias)}transaction_class <> 'internal_transfer'"


# ---------------------------------------------------------------------------
# Privacy & sandbox filters
# ---------------------------------------------------------------------------
def private_visibility_filter(alias: str, idx: int) -> str:
    """
    SQL fragment that hides another user's private transactions from the
    requesting viewer. Returns ``""`` when the caller passes
    ``viewer_user_id=None`` (internal jobs, startup migrations, tests).

    The ``$idx`` placeholder is asyncpg-style. Caller is responsible for
    appending the matching ``viewer_user_id`` to the params list.

    Example:
        params = [month]
        if viewer_user_id is not None:
            params.append(viewer_user_id)
        sql = f"... {private_visibility_filter('t', 2) if viewer_user_id else ''}"
    """
    prefix = _qualify(alias)
    return (
        f" AND (NOT {prefix}is_private OR EXISTS ("
        f"SELECT 1 FROM accounts _pa WHERE _pa.id = {prefix}account_id "
        f"AND _pa.user_id = ${idx}))"
    )


def sandbox_exclusion_filter(alias: str = "t") -> str:
    """
    SQL fragment that drops Plaid-sandbox-flagged rows when the runtime
    toggle says they shouldn't appear in reports. Returns ``""`` when
    sandbox inclusion is on (sandbox env, or explicit override).

    Reads :func:`web.env_flags.reports_include_plaid_sandbox` at call time
    so deploy-time env changes take effect on the next request without an
    app restart. Pass ``alias=""`` for unaliased queries (e.g. inside
    ``WHERE … FROM transactions`` without a ``t`` alias).
    """
    if reports_include_plaid_sandbox():
        return ""
    prefix = _qualify(alias)
    return f" AND ({prefix}source IS NULL OR {prefix}source <> 'plaid_sandbox')"
