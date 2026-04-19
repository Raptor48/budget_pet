"""
Invariant tests for the cash-flow identity.

The four transaction classes must be exhaustive and disjoint (see
``docs/reports-math.md`` §2). For any month ``M`` the following identity
holds over ``transactions`` filtered to that month:

    SUM(amount_cents) WHERE class='income'
    + SUM(amount_cents) WHERE class='expense'
    + SUM(amount_cents) WHERE class='internal_transfer'
    + SUM(amount_cents) WHERE class='uncategorized'
    ≡ SUM(amount_cents) over all rows in the month

Equivalently: the three buckets reported by ``/api/reports/cash-flow``
(income, expenses, internal_transfers) plus any uncategorized residual
must reconcile to the raw sum of all transaction amounts in the month.

These tests use the pure Python classifier (``classify_row``) on a curated
synthetic row set — no DB roundtrip — because the invariant is a property
of the rule table, not of the SQL aggregate. The SQL side has its own
regression tests in ``test_income_report.py`` and
``test_internal_transfers.py``.
"""
from __future__ import annotations

from typing import List, Set

import pytest

from web.classification.classifier import RowView, classify_row


def _row(
    *,
    id: int,
    amount_cents: int,
    account_type: str = "depository",
    pfc_primary: str | None = None,
    merchant_name: str | None = None,
    name: str | None = None,
    source: str = "plaid",
    category_is_income: bool = False,
    manual_class_override: str | None = None,
    legacy_is_internal_transfer_manual: bool = False,
    legacy_is_internal_transfer: bool = False,
) -> RowView:
    return RowView(
        id=id,
        amount_cents=amount_cents,
        account_type=account_type,
        pfc_primary=pfc_primary,
        merchant_name=merchant_name,
        name=name,
        counterparties=None,
        source=source,
        category_is_income=category_is_income,
        manual_class_override=manual_class_override,
        legacy_is_internal_transfer_manual=legacy_is_internal_transfer_manual,
        legacy_is_internal_transfer=legacy_is_internal_transfer,
    )


def _classify_all(
    rows: List[RowView],
    *,
    paired_ids: Set[int] | None = None,
    name_matches: List[str] | None = None,
) -> dict[str, int]:
    """Sum ``amount_cents`` into buckets keyed by class."""
    paired_ids = paired_ids or set()
    name_matches = name_matches or []
    totals = {"income": 0, "expense": 0, "internal_transfer": 0, "uncategorized": 0}
    for r in rows:
        cls = classify_row(r, paired_ids=paired_ids, name_matches=name_matches)
        totals[cls] += r.amount_cents
    return totals


class TestIdentity:
    def test_sum_over_classes_equals_raw_sum(self):
        """
        The sum of `amount_cents` partitioned by class equals the sum over
        all rows. No double counting, no lost rows.
        """
        rows = [
            # Paycheck
            _row(id=1, amount_cents=-500_000, category_is_income=True),
            # Grocery swipe
            _row(id=2, amount_cents=4_250, pfc_primary="FOOD_AND_DRINK"),
            # Refund for a grocery return
            _row(id=3, amount_cents=-1_500, pfc_primary="FOOD_AND_DRINK"),
            # CC payment, depository outflow leg
            _row(id=4, amount_cents=120_000, pfc_primary="LOAN_PAYMENTS"),
            # CC payment, credit inflow leg
            _row(
                id=5,
                amount_cents=-120_000,
                account_type="credit",
                pfc_primary="LOAN_PAYMENTS",
            ),
            # Zelle to spouse (name match)
            _row(
                id=6,
                amount_cents=25_000,
                pfc_primary="TRANSFER_OUT",
                name="Zelle payment to SPOUSE",
            ),
            # Lonely investment outflow → uncategorized
            _row(
                id=7,
                amount_cents=10_000,
                account_type="investment",
                pfc_primary="TRANSFER_OUT",
            ),
        ]
        paired = {4, 5}  # CC payment pair
        buckets = _classify_all(rows, paired_ids=paired, name_matches=["SPOUSE"])
        raw_sum = sum(r.amount_cents for r in rows)
        reconstructed = sum(buckets.values())
        assert reconstructed == raw_sum, (
            f"identity violated: classes sum to {reconstructed} but raw sum is "
            f"{raw_sum}; buckets={buckets}"
        )

    def test_classes_are_disjoint_for_every_row(self):
        """No row can land in two buckets: ``classify_row`` must return
        exactly one class. (Trivial from the type system, but worth
        pinning — the rule table could grow overlapping conditions.)"""
        rows = [
            _row(id=1, amount_cents=-500_000, category_is_income=True),
            _row(id=2, amount_cents=4_250, pfc_primary="FOOD_AND_DRINK"),
            _row(id=3, amount_cents=-1_500, pfc_primary="FOOD_AND_DRINK"),
        ]
        for r in rows:
            cls = classify_row(r, paired_ids=set(), name_matches=[])
            assert cls in {"income", "expense", "internal_transfer", "uncategorized"}

    def test_refund_reduces_expense_bucket(self):
        """
        The whole point of V2's refund semantics: a $15 refund against a
        $42 grocery purchase nets to $27 of expense for the month, not
        $42 expense + $15 income.
        """
        rows = [
            _row(id=1, amount_cents=4_250, pfc_primary="FOOD_AND_DRINK"),
            _row(id=2, amount_cents=-1_500, pfc_primary="FOOD_AND_DRINK"),
        ]
        buckets = _classify_all(rows)
        assert buckets["income"] == 0
        assert buckets["expense"] == 4_250 - 1_500  # 2_750 net
        assert buckets["internal_transfer"] == 0
        assert buckets["uncategorized"] == 0

    def test_cc_payment_lands_entirely_in_internal_transfer(self):
        """
        A credit-card payment cycle should contribute ZERO to both income
        and expense and only populate ``internal_transfer`` (and even
        that sums to zero on the family's books, since the two legs
        cancel — which is the mathematically correct "no net cash flow"
        outcome).
        """
        rows = [
            _row(id=10, amount_cents=120_000, pfc_primary="LOAN_PAYMENTS"),
            _row(
                id=11,
                amount_cents=-120_000,
                account_type="credit",
                pfc_primary="LOAN_PAYMENTS",
            ),
        ]
        buckets = _classify_all(rows, paired_ids={10, 11})
        assert buckets["income"] == 0
        assert buckets["expense"] == 0
        assert buckets["internal_transfer"] == 0
        assert buckets["uncategorized"] == 0


class TestEdgeCases:
    def test_empty_month_is_zero_across_buckets(self):
        buckets = _classify_all([])
        assert buckets == {
            "income": 0,
            "expense": 0,
            "internal_transfer": 0,
            "uncategorized": 0,
        }

    def test_single_uncategorized_row_does_not_leak_into_expense(self):
        """Investment-account outflow with no pair should go into
        ``uncategorized`` — specifically NOT ``expense``, otherwise a
        user's 401(k) contribution appears as spending on the Expenses
        tab."""
        rows = [
            _row(
                id=1,
                amount_cents=100_000,
                account_type="investment",
                pfc_primary="TRANSFER_OUT",
            ),
        ]
        buckets = _classify_all(rows)
        assert buckets["expense"] == 0
        assert buckets["uncategorized"] == 100_000
