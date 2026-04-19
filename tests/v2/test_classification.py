"""
Tests for the core transaction classifier (``web/classification/classifier.py``).

Scope (matches the rule table in ``docs/reports-math.md`` §3):

    1. Manual override beats everything.
    2. Cash ↔ debt pair (credit-card payment, loan payment).
    3. Depository ↔ depository pair (Plaid TRANSFER_OUT / TRANSFER_IN).
    4. Zelle-style counterparty name hit.
    5. Income category + negative amount → income; positive amount →
       uncategorized (sign mismatch is a data-quality flag).
    6. Depository / credit / cash outflow that is not a transfer → expense
       (refunds with negative sign stay in ``expense`` and reduce the
       month's total).
    7. Investment / loan rows that did not pair → uncategorized.

We exercise ``classify_row`` as a pure function with hand-built ``RowView``
fixtures — no DB involved — because the SQL side (``match_pairs``,
``rescan_all``) is exercised by the live-Postgres integration tests and by
the SQL-contract tests in ``test_internal_transfers.py``.
"""
from __future__ import annotations

from typing import Set

import pytest

from web.classification.classifier import RowView, classify_row


def _row(
    *,
    id: int = 1,
    amount_cents: int = 10_000,
    account_type: str = "depository",
    pfc_primary: str | None = None,
    merchant_name: str | None = None,
    name: str | None = None,
    counterparties=None,
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
        counterparties=counterparties,
        source=source,
        category_is_income=category_is_income,
        manual_class_override=manual_class_override,
        legacy_is_internal_transfer_manual=legacy_is_internal_transfer_manual,
        legacy_is_internal_transfer=legacy_is_internal_transfer,
    )


class TestRule1ManualOverride:
    """Rule 1: user pin wins over every other rule."""

    @pytest.mark.parametrize(
        "override",
        ["income", "expense", "internal_transfer", "uncategorized"],
    )
    def test_override_beats_all_other_rules(self, override: str):
        # A row that would otherwise be an expense (depository outflow) —
        # but the user pinned it. The pin wins no matter what.
        row = _row(
            amount_cents=10_000,
            account_type="depository",
            pfc_primary="FOOD_AND_DRINK",
            manual_class_override=override,
        )
        assert classify_row(row, paired_ids=set(), name_matches=[]) == override

    def test_legacy_internal_transfer_manual_preserved(self):
        """
        Rows flipped to "Internal transfer" in the old UI before the
        migration must keep that class forever — the classifier falls back
        to the legacy boolean pair even when ``manual_class_override`` is
        still NULL on a freshly-imported row.
        """
        row = _row(
            legacy_is_internal_transfer_manual=True,
            legacy_is_internal_transfer=True,
            account_type="depository",
            amount_cents=10_000,
        )
        assert classify_row(row, paired_ids=set(), name_matches=[]) == "internal_transfer"

    def test_legacy_manual_off_is_ignored(self):
        """Half-set legacy flags (manual=True, is_transfer=False) are
        meaningless — the code must fall through to the rest of the rules
        rather than honor them."""
        row = _row(
            legacy_is_internal_transfer_manual=True,
            legacy_is_internal_transfer=False,
            account_type="depository",
            amount_cents=10_000,
        )
        assert classify_row(row, paired_ids=set(), name_matches=[]) == "expense"


class TestRulesTwoAndThreePairMatched:
    """Rules 2 + 3: any row present in ``paired_ids`` is an internal transfer."""

    def test_cc_payment_outflow_paired_is_transfer(self):
        # Depository outflow (amount > 0) with LOAN_PAYMENTS pfc → classic
        # credit-card-bill pay. Pair matcher flagged it.
        row = _row(
            id=42,
            amount_cents=120_000,
            account_type="depository",
            pfc_primary="LOAN_PAYMENTS",
        )
        paired: Set[int] = {42, 43}
        assert classify_row(row, paired_ids=paired, name_matches=[]) == "internal_transfer"

    def test_cc_payment_inflow_partner_is_transfer(self):
        # The credit side of the same bill-pay: credit account, negative
        # amount, PFC usually LOAN_PAYMENTS_CREDIT_CARD_PAYMENT.
        row = _row(
            id=43,
            amount_cents=-120_000,
            account_type="credit",
            pfc_primary="LOAN_PAYMENTS",
        )
        paired: Set[int] = {42, 43}
        assert classify_row(row, paired_ids=paired, name_matches=[]) == "internal_transfer"

    def test_depository_transfer_out_paired_is_transfer(self):
        # Savings → Checking sweep — Plaid TRANSFER_OUT / TRANSFER_IN.
        row = _row(
            id=11,
            amount_cents=50_000,
            account_type="depository",
            pfc_primary="TRANSFER_OUT",
        )
        assert (
            classify_row(row, paired_ids={11, 12}, name_matches=[])
            == "internal_transfer"
        )

    def test_unpaired_transfer_falls_through(self):
        """A lone TRANSFER_OUT without a matching TRANSFER_IN (and no name
        match) should NOT be counted as internal — rule 6 wraps it in
        ``expense`` where the user can see and re-tag it."""
        row = _row(
            id=99,
            amount_cents=50_000,
            account_type="depository",
            pfc_primary="TRANSFER_OUT",
        )
        assert classify_row(row, paired_ids=set(), name_matches=[]) == "expense"


class TestRule4NameMatch:
    """Rule 4: counterparty name hit in ``internal_transfer_names``."""

    def test_zelle_name_match_is_internal_transfer(self):
        row = _row(
            pfc_primary="TRANSFER_IN",
            merchant_name=None,
            name="Zelle payment from ANASTASIIA STOLPOVSKAIA",
            amount_cents=-50_000,
            account_type="depository",
        )
        result = classify_row(
            row, paired_ids=set(), name_matches=["ANASTASIIA STOLPOVSKAIA"]
        )
        assert result == "internal_transfer"

    def test_non_transfer_pfc_is_not_name_matched(self):
        """Even if the counterparty name would match, a non-TRANSFER_* PFC
        row is never classified as internal by the name rule alone. The
        classifier defers to ``classify_internal_transfer``, which itself
        gates on the PFC."""
        row = _row(
            pfc_primary="FOOD_AND_DRINK",
            merchant_name="ANASTASIIA STOLPOVSKAIA",
            amount_cents=5_000,
            account_type="depository",
        )
        assert (
            classify_row(
                row, paired_ids=set(), name_matches=["ANASTASIIA STOLPOVSKAIA"]
            )
            == "expense"
        )


class TestRule5IncomeByCategory:
    """Rule 5: category ``is_income=TRUE`` + amount negative → income."""

    def test_paycheck_is_income(self):
        row = _row(
            amount_cents=-500_000,  # credit side: money in
            account_type="depository",
            pfc_primary="INCOME",
            category_is_income=True,
        )
        assert classify_row(row, paired_ids=set(), name_matches=[]) == "income"

    def test_income_category_with_positive_amount_is_uncategorized(self):
        """Sign mismatch: category is flagged income but the amount is a
        debit. Most likely a refund miscategorized into INCOME or a
        TRANSFER that took the INCOME bucket. Surface in diagnostics,
        never count as income."""
        row = _row(
            amount_cents=5_000,  # debit on an income-tagged category
            account_type="depository",
            category_is_income=True,
        )
        assert classify_row(row, paired_ids=set(), name_matches=[]) == "uncategorized"


class TestRule6ExpenseFallback:
    """Rule 6: spendable-account rows that did not pair → expense. Refunds
    stay in ``expense`` with a negative amount so month totals net out."""

    def test_grocery_swipe_is_expense(self):
        row = _row(
            amount_cents=4_250,
            account_type="depository",
            pfc_primary="FOOD_AND_DRINK",
        )
        assert classify_row(row, paired_ids=set(), name_matches=[]) == "expense"

    def test_credit_card_swipe_is_expense(self):
        # Positive on a credit card = swipe (more liability).
        row = _row(
            amount_cents=9_999,
            account_type="credit",
            pfc_primary="GENERAL_MERCHANDISE",
        )
        assert classify_row(row, paired_ids=set(), name_matches=[]) == "expense"

    def test_cash_row_is_expense(self):
        row = _row(
            amount_cents=2_000,
            account_type=None,  # cash wallet may come back as None
            source="cash",
        )
        assert classify_row(row, paired_ids=set(), name_matches=[]) == "expense"

    def test_refund_stays_in_expense_bucket(self):
        """A negative-amount row on a non-income category is a refund. It
        stays classified as ``expense`` — the sign itself makes the month
        total go down when SUM(amount_cents) is aggregated. If the
        classifier moved refunds into ``income`` they would inflate income
        AND leave the original category's spend unchanged."""
        row = _row(
            amount_cents=-3_000,
            account_type="depository",
            pfc_primary="GENERAL_MERCHANDISE",
            category_is_income=False,
        )
        assert classify_row(row, paired_ids=set(), name_matches=[]) == "expense"


class TestRule7Uncategorized:
    """Rule 7: investment / loan rows that did not pair fall through to
    ``uncategorized`` rather than polluting expense totals."""

    def test_investment_outflow_unpaired_is_uncategorized(self):
        row = _row(
            amount_cents=100_000,
            account_type="investment",
            pfc_primary="TRANSFER_OUT",
        )
        assert (
            classify_row(row, paired_ids=set(), name_matches=[])
            == "uncategorized"
        )

    def test_loan_outflow_unpaired_is_uncategorized(self):
        row = _row(
            amount_cents=50_000,
            account_type="loan",
            pfc_primary="LOAN_PAYMENTS",
        )
        assert (
            classify_row(row, paired_ids=set(), name_matches=[])
            == "uncategorized"
        )


class TestRulePriorityMatrix:
    """Cross-cutting tests that pin the rule ORDER — not just individual
    outcomes. If someone reorders the rules, at least one of these fires."""

    def test_manual_override_beats_pair_match(self):
        """Even if the pair matcher found a partner, an explicit
        `manual_class_override='expense'` wins (user said it was a real
        purchase even if Plaid's pair matcher disagrees)."""
        row = _row(
            id=42,
            amount_cents=10_000,
            account_type="depository",
            manual_class_override="expense",
        )
        assert classify_row(row, paired_ids={42, 43}, name_matches=[]) == "expense"

    def test_pair_match_beats_name_match(self):
        """A row that both pairs AND matches a name still lands in
        ``internal_transfer`` — no ambiguity because both rules would push
        it there anyway. This just guards against a regression that skips
        the ``paired_ids`` check when name_matches is populated."""
        row = _row(
            id=42,
            pfc_primary="TRANSFER_IN",
            name="Zelle payment from SPOUSE",
            amount_cents=-10_000,
            account_type="depository",
        )
        assert (
            classify_row(row, paired_ids={42}, name_matches=["SPOUSE"])
            == "internal_transfer"
        )

    def test_pair_match_beats_income_category(self):
        """If a TRANSFER_IN landed on an (incorrectly) income-flagged
        category AND paired with a TRANSFER_OUT, pair match wins — the
        money is internal, not income."""
        row = _row(
            id=42,
            amount_cents=-50_000,
            account_type="depository",
            pfc_primary="TRANSFER_IN",
            category_is_income=True,  # user tagged the TRANSFER_IN category
        )
        assert (
            classify_row(row, paired_ids={42}, name_matches=[])
            == "internal_transfer"
        )

    def test_income_category_beats_expense_fallback(self):
        """A paycheck arriving on a depository account would otherwise look
        like a negative-amount expense. The income-category check must run
        before the expense fallback."""
        row = _row(
            amount_cents=-500_000,
            account_type="depository",
            category_is_income=True,
        )
        assert classify_row(row, paired_ids=set(), name_matches=[]) == "income"
