"""
Transaction classification — single source of truth for what counts as income,
expense and internal transfer across the app.

See ``docs/reports-math.md`` for the full specification of the four classes
and their invariants. The public surface is intentionally small:

* ``TransactionClass`` — the enum of legal class values.
* ``classify_row`` — pure function that decides one row's class from its
  already-materialized fields plus pre-computed pair / name-match hints.
* ``match_pairs`` — find cross-account internal-transfer pairs (cash ↔ debt,
  depository ↔ depository) within a date horizon.
* ``rescan_all`` — re-classify every non-manual-override row in the DB.
* ``classify_one_on_insert`` — helper used by Plaid sync and the cash API to
  compute the class for a freshly-inserted row in-process.
"""
from .classifier import (
    ALL_CLASSES,
    TransactionClass,
    classify_row,
    classify_one_on_insert,
    match_pairs,
    rescan_all,
)

__all__ = [
    "ALL_CLASSES",
    "TransactionClass",
    "classify_row",
    "classify_one_on_insert",
    "match_pairs",
    "rescan_all",
]
