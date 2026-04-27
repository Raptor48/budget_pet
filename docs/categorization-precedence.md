# Budget Pet — Categorization & classification precedence

This is the **single source of truth** for "which mechanism wins when two
of them touch the same transaction". Two related but distinct fields on
`transactions` are governed by separate rule chains:

| Field | What it answers | Sets it |
|---|---|---|
| `category_id` | _What kind of spend / income is this?_ | PFC mapping → merchant rules → manual edit → splits |
| `transaction_class` | _Income, expense, internal transfer, or uncategorized?_ | The classifier (`web/classification/classifier.py`), 7 rules in priority order |

Display-only overlays (`merchant_aliases`, `tags`) are layered on read
without touching either field.

If code in this repo contradicts this doc, **fix the code or update the
doc**. Never silently drift.

## 1. `category_id` — write-time precedence

The order in which mechanisms can write `category_id`. Lower-numbered
mechanisms set the field first; higher-numbered ones override it,
**except where explicitly preserved**.

| # | Mechanism | When it writes | Wins over | Preserved by sync? |
|---|---|---|---|---|
| 1 | **PFC mapping** | On every `INSERT` of a Plaid transaction | nothing (it sets the initial value) | n/a (this is the sync step) |
| 2 | **Merchant rule** (`merchant_category_rules`) | On `INSERT` only — applied by `web/plaid/repo.py::import_transactions` | PFC | yes — sync `UPDATE` does not re-apply rules |
| 3 | **Manual edit** (`PATCH /api/transactions/{id}`) | When the user picks a category in the Transaction Details modal | both PFC and merchant rules | **yes** — see "manual edits survive sync" below |
| 4 | **Pending → posted carry-over** | When a pending row is replaced by its posted twin during Plaid sync | merchant rule's `rule_cat` is checked first; the pending category only fills in when no rule matched | n/a (this is the sync step itself) |
| 5 | **Splits** (`transaction_splits`) | When the user splits a transaction across categories | the parent's `category_id` becomes informational only — repos that aggregate spend look at the rows in `transaction_splits` instead | yes — splits live in their own table |

### Manual edits survive sync

The Plaid import upsert in `web/plaid/repo.py::import_transactions` uses

```sql
ON CONFLICT (plaid_transaction_id) DO UPDATE SET
  category_id = COALESCE(transactions.category_id, EXCLUDED.category_id),
  ...
```

The `COALESCE` is the contract: an existing non-NULL `category_id` is
**never** overwritten by a sync. So if the user manually picks "Rent" on
a row, every subsequent sync of that row leaves the category alone. The
EXCLUDED side only fills in when the existing column is `NULL` (e.g. a
brand-new transaction whose PFC didn't map to any category).

This is also why merchant rules don't re-fire on update: by design the
`apply_rule_to_transactions` job (Settings → "Apply existing") is the
**only** explicit way to retroactively re-run a rule, and it preserves
custom-category rows by checking `categories.source = 'plaid_pfc'`
before updating (see `web/merchant_rules/apply.py:_preview_conn`).

### How to make a per-row category that the rule doesn't override

Any of:

1. PATCH the row directly via the Transaction Details modal — sticky.
2. Don't set up a rule that would match the row in the first place.
3. If a too-broad merchant rule already exists, narrow it via the
   description-filter option (see [§3](#3-narrowing-a-rule-without-creating-a-new-one)).

## 2. `transaction_class` — classifier precedence

The classifier (`web/classification/classifier.py::classify_row`)
decides between `income`, `expense`, `internal_transfer`, and
`uncategorized`. Rules run top-down and the first match wins. The
authoritative description lives in [`reports-math.md`](./reports-math.md);
this is the abridged precedence ladder:

1. **`manual_class_override`** — per-row pin set by the user via the
   class dropdown in Transaction Details. Never second-guessed.
2. **Cash ↔ debt pair match** — outflow on a depository account paired
   with the matching inflow on a credit / loan account within ±3 days,
   **same family member on both legs**.
3. **Depository ↔ depository pair match** — classic
   `TRANSFER_OUT` / `TRANSFER_IN` cross-account move, **same family
   member on both legs**. Cross-spouse moves are handled by rule 4
   (counterparty name match), not by this matcher.
4. **Counterparty name match** — `app_settings.internal_transfer_names`
   contains the counterparty (e.g. a spouse's name on Zelle).
5. **`category.is_income`** — the assigned category is flagged as income
   AND the row is a credit (`amount_cents < 0`).
6. **Orphan inbound depository transfer** — `TRANSFER_IN` that didn't
   pair and didn't name-match. Treated as income, not expense refund.
7. **Spendable-account fallback** — depository / credit / cash outflow
   that isn't a transfer becomes an expense.
8. **Uncategorized** — investment / loan rows that didn't pair, etc.

## 3. Narrowing a rule without creating a new one

Merchant rules support an optional `description_contains` filter (see
`web/merchant_rules/repo.py`). The matching SQL prefers the most
specific rule:

```
ORDER BY description_contains IS NULL  -- non-null first wins
```

So given two rules on the same merchant:

| `merchant_key` | `description_contains` | `category_id` |
|---|---|---|
| `name:zelle` | NULL | Transfer Out |
| `name:zelle` | `alla` | Rent |

A row with `name = "Zelle payment to ALLA 24800561672"` matches both,
but the `alla`-filtered row wins because it's more specific. A
generic Zelle row (no `ALLA` in description) only matches the first
and goes to Transfer Out.

The Transaction Details "Always categorize like this" button suggests
a description filter automatically when it detects multiple distinct
descriptions for the same merchant in recent history — see
`apply.py::preview_match_count`.

## 4. Cross-mechanism interactions to be aware of

These are the surprising-but-correct combinations that have caused
confusion in the past. Each one has either a UI guard or a documented
expected behavior.

### `transaction_class` is the only "is this internal" source of truth

The `transactions.is_internal_transfer BOOLEAN` column predates the
4-class model and is kept in the schema as a mirror only — every classifier
update (`rescan_all`, `classify_one_on_insert`, manual override) writes
both columns in lockstep:

```sql
UPDATE transactions SET
  transaction_class    = $2,
  is_internal_transfer = ($2 = 'internal_transfer'),
  ...
```

**All UI code must read from `transaction_class`, not `is_internal_transfer`.**
Until 2026-04-27 the desktop and mobile transaction list rows rendered
the "INTERNAL" pill straight off the legacy boolean. That worked in the
steady state but produced a visible inconsistency for a few seconds (or
permanently, until a manual full rescan) on rows that were INSERTed
with `is_internal_transfer = TRUE` (counterparty-name match at write
time) but whose `transaction_class` was still the default
`'uncategorized'` because the post-import rescan only covered the last
7 days. See "Post-import rescan covers full history" below.

### Post-import rescan covers full history

`web/plaid/repo.py::import_transactions` runs `rescan_all(conn,
horizon_days=None)` after every Plaid import, not just the last 7 days
as it did before 2026-04-27. The 7-day window was a perf shortcut for
incremental syncs of an existing item, but `transactions/sync` returns
the full available history on the **first** sync of a freshly-added
item — often 30+ days. Rows older than the 7-day window were being
inserted with the legacy mirror set correctly but `transaction_class`
left at the default `'uncategorized'`, so they leaked into the
inconsistent state described above and into the wrong aggregates
(Income would pick them up via classifier rule 5.5 — orphan TRANSFER_IN
on a depository account → income — once the rescan finally ran
without the horizon).

A full rescan completes in under a second for typical family histories
(~50k rows). Manual class overrides are always preserved by classifier
rule 1, so user decisions stay sacred.

`_migrate_fix_internal_transfer_class_drift` runs on app startup with
**two triggers**:

1. **One-shot sentinel** `app_settings.itr_v2_rescan_done` — when
   `FALSE` (first deploy of this fix), force a full rescan
   unconditionally and flip to `TRUE`. This catches stale-but-self-
   consistent rows, e.g. those that classifier rule 5.5 tagged as
   `income` on a previous rescan when the counterparty-name list was
   empty: the legacy + modern columns agree (`FALSE` ↔ "not internal")
   but the row is now wrong relative to the current names list. A
   column-drift probe alone misses these.
2. **Drift probe** — column-level safety net that runs on every
   startup. Triggers a rescan whenever `is_internal_transfer <>
   (transaction_class = 'internal_transfer')` for any non-manual row.
   Catches future regressions (e.g. an INSERT path that re-introduces
   the column-skip bug).

Manual class overrides are excluded from both triggers and preserved
by `classify_row` rule 1, so user decisions stay sacred. On a steady-
state install (sentinel TRUE, no drift) the migration is two cheap
`fetchval`s and a return.

### `transaction_class = 'internal_transfer'` AND `category_id IS NOT NULL`

The category is **set but not used** in spending aggregates. Cash Flow,
By Category, Reports → Expenses all filter on
`transaction_class = 'expense'`, so an internal-transfer row never
contributes — even if its category is, say, "Rent".

**UI guard:** the Transaction Details modal shows an inline amber
warning whenever this combination is detected, with a hint to flip the
class override to `Auto` or `Expense` if the row should count as
real spend.

**Why this isn't a bug:** internal transfers between family accounts
(spouse Zelle, savings → checking) genuinely shouldn't count toward
expenses — they don't change household net worth. The category just
provides a label for the user's own bookkeeping.

### `category.is_income = TRUE` AND row is a debit

Classifier rule 5 detects this and falls through to `uncategorized`
instead of either `income` or `expense`. Surfaces in the diagnostics
endpoint so power users can spot miscategorized refunds.

### Merchant alias survives bank disconnect

Aliases live on `merchant_key` (Plaid's stable merchant id), not on a
specific `transactions` row, so they survive a disconnect-and-reconnect
cycle. If you renamed "STARBUCKS" → "Coffee" while connected to Bank A
and later reconnect via Bank B, the new Starbucks transactions
automatically pick up the rename.

This is intentional. If you want to reset, delete the alias from the
Transaction Details modal (RENAME MERCHANT → clear).

### Splits + parent `category_id`

When a transaction has rows in `transaction_splits`, every aggregate
read (reports, budgets, top categories) operates on the splits and
**ignores the parent's `category_id`**. The parent column becomes a
no-op until all splits are removed. Repos enforce this with a
`NOT EXISTS (SELECT 1 FROM transaction_splits ts WHERE ...)`
clause around any rule-application or category-rollup query.

### Manual class override + later rule change

`manual_class_override` is checked first by the classifier (rule 1) and
is **never** modified by the classifier itself. Editing a merchant rule
or the internal-transfer name list does not unstick a row that was
manually pinned. To clear it, set the class dropdown back to "Auto" in
the Transaction Details modal.

## 5. Quick reference: where to look in code

| Behavior | File |
|---|---|
| PFC mapping (Plaid → category) | `web/categories/pfc_mapping.py` |
| Merchant rule lookup (apply on import) | `web/merchant_rules/repo.py::lookup_category` |
| Merchant rule re-apply (Settings button) | `web/merchant_rules/apply.py::apply_rule_to_transactions` |
| Description-filter heuristic (preview) | `web/merchant_rules/apply.py::preview_match_count` |
| Manual category PATCH | `web/transactions/routes.py::update_transaction` |
| Splits-aware aggregation | `web/reports/repo.py` (every `by_category` / `cash_flow` query) |
| Classifier (the 7-rule ladder) | `web/classification/classifier.py::classify_row` |
| Internal-transfer name list | `web/internal_transfers/repo.py` |
| Manual class override (per-row pin) | `transactions.manual_class_override` column |
| Merchant alias (display rename) | `web/merchant_rules/aliases.py` |
| Tags (free-form labels) | `web/tags/` |

If you add an eighth mechanism, **update this doc in the same PR**.
