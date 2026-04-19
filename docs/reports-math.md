# Budget Pet V2 — Reports Math

This document is the **source of truth** for how money flowing through the app
is classified and aggregated. Every report, chart, budget and health metric
reads from the same invariants defined below. If behavior in code contradicts
this document, code is wrong — either fix the code or update the doc (after
discussion), never silently drift.

## 1. The four classes

Every row in `transactions` belongs to exactly one of:

| Class | Meaning | Examples |
|---|---|---|
| `income` | Money flowing **into** the family from outside | Paycheck, freelance, interest earned, cash-back, external ACH, refund from an external income source |
| `expense` | Money flowing **out of** the family to an external party | Grocery swipe, coffee, subscription, mortgage payment when the loan is **not** tracked as a family liability, fees |
| `internal_transfer` | Money moving **between the family's own tracked accounts** | Checking → Savings, credit-card payment, loan payment to a family loan account, Zelle between spouses |
| `uncategorized` | Classifier declined to pick a class (rare) | Investment-account outflow/inflow that does not pair, debit on a depository with a category flagged as income but amount > 0 (corrupted signal) |

The class lives on `transactions.transaction_class` and is **materialized on
insert** by `web.classification.classifier.classify_row`, and on re-scan by
`classify.rescan_all`. Manual user overrides are stored in
`transactions.manual_class_override` and always win.

## 2. Invariants

1. **Exhaustive & disjoint** — every transaction has exactly one class. No
   row is in two classes, no row is classless. New classes require a migration
   and a code review of every consumer.
2. **Cash-flow identity** — for any period and any scope (family, user, set of
   accounts) the following holds before any sign flipping:

   ```
   SUM(amount_cents) = (sum over class='expense') + (sum over class='income') + (sum over class='internal_transfer') + (sum over class='uncategorized')
   ```

   The `/api/reports/cash-flow` endpoint surfaces the three non-uncategorized
   buckets; `uncategorized` is surfaced in `/api/reports/diagnostics` so the
   user can fix misclassifications.
3. **Net-worth identity** — over any period `Δ(liquid + investment - debt) ≈
   income - expense` (± market revaluation on investment holdings and rounding).
   `internal_transfer` must not move the right-hand side — it cancels out
   between two family accounts.
4. **Refunds reduce the category they came from** — `amount_cents < 0` on an
   `expense` row stays in `expense` with a negative amount. Monthly expense
   aggregates therefore use `SUM(amount_cents)` (not `SUM(amount_cents) WHERE
   amount > 0`); rebates, chargebacks and returns naturally decrease the
   month.
5. **Manual overrides are sacred** — once the user sets
   `manual_class_override`, auto-classification never touches that row. The
   legacy `is_internal_transfer_manual = TRUE` sentinel is honored by the new
   classifier during migration and beyond.
6. **Sandbox parity** — every aggregate used for analytics (cash-flow,
   income, expenses, by-category, by-tag, merchants, budgets, health,
   diagnostics) respects `reports_include_plaid_sandbox()` the same way. The
   only exception is the transactions **list** endpoint which intentionally
   shows sandbox rows to the user regardless of the flag.
7. **Privacy** — `is_private` rows belonging to other family members are
   excluded from every aggregate whose API has a `viewer_user_id`; the
   diagnostics endpoint is owner-only and ignores the filter.

## 3. Classification rules (priority order)

Implemented in `web.classification.classifier.classify_row`:

1. **Manual override.** If `manual_class_override` is set, use it verbatim.
2. **Pair match — cash ↔ debt.** An outflow (`amount_cents > 0`) on a
   `depository` account with `pfc_primary IN ('LOAN_PAYMENTS', 'TRANSFER_OUT')`
   is paired with an inflow (`amount_cents < 0` of equal magnitude) on a
   `credit` or `loan` account within ±3 days. Both rows → `internal_transfer`.
   This is the rule that fixes the historical undercount of credit-card
   payments from checking accounts.
3. **Pair match — depository ↔ depository.** Classic
   `TRANSFER_OUT` / `TRANSFER_IN` pair between two different family depository
   accounts within ±3 days. Both rows → `internal_transfer`.
4. **Name match.** `pfc_primary IN ('TRANSFER_IN', 'TRANSFER_OUT')` with a
   counterparty name matching the family-wide
   `app_settings.internal_transfer_names` list (Zelle between spouses etc.).
   → `internal_transfer`.
5. **Income by category.** `categories.is_income = TRUE` AND
   `amount_cents < 0` → `income`. A row whose category is flagged income but
   whose sign says debit (`amount > 0`) is **not** silently reclassified —
   it becomes `uncategorized` so the inconsistency surfaces in diagnostics.
6. **Expense fallback.** Any remaining row on a `depository`, `credit`,
   `other` account or `source = 'cash'` → `expense`. Sign is preserved, so
   refunds (`amount < 0`) stay in expense and reduce the aggregate.
7. **Uncategorized.** Rows on `investment` or `loan` accounts that did not
   match pair/name rules are left uncategorized. These represent internal
   investment movements that we do not yet have strong enough signals for;
   they can be overridden manually if needed.

## 4. Splits

`transaction_splits` inherits the parent's classification. A split row
contributes to the same class as its parent (`t.transaction_class`), while the
split's own `category_id` is used for the category-level breakdown. The SUM
invariant `SUM(splits.amount_cents) = parent.amount_cents` is preserved
(guaranteed by the splits API), so per-class totals are unchanged when a
transaction is split.

## 5. What changed vs. V2.1

Before this document existed, expense aggregates used `amount_cents > 0 AND
NOT is_internal_transfer` everywhere. This had two failure modes:

1. Refunds (`amount_cents < 0` on a non-income category) were silently ignored
   instead of reducing the month's spend.
2. Credit-card payments from checking accounts — the most common "internal
   transfer" in a typical US household — were counted as expenses because
   Plaid returns them with `pfc_primary = 'LOAN_PAYMENTS'`, which the old
   pair-matcher (`TRANSFER_OUT` / `TRANSFER_IN` only) did not recognize. This
   inflated the monthly expenses by roughly the sum of all credit-card bills.

Replacing those filters with `transaction_class = 'expense'` + `SUM(amount_cents)`
fixes both. Existing users see a drop in reported monthly expenses on the
migration run — this is expected and documented in the release notes.

## 6. Open questions (intentional non-goals for V2.2)

- **Mortgage interest vs. principal split.** We do not split loan payments
  between interest (true expense) and principal (debt reduction). If the
  user has the loan account linked in Plaid, the whole payment is
  `internal_transfer` and net worth math is accurate. If they do not, the
  payment is `expense` and includes principal; users accept this trade-off.
- **Investment cashflows.** Transfers into brokerage accounts (401k, IRA
  contributions) are `uncategorized` by default. Future work may add
  `depository ↔ investment` pair matching.
- **Category-level class overrides.** If many users end up setting the same
  `manual_class_override` on transactions from the same category (e.g. all
  `LOAN_PAYMENTS_CAR_PAYMENT` to internal because they treat the car as a
  family asset), a `categories.classification_override` field may be added.
  Not yet on the roadmap.
