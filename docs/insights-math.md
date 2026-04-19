# Budget Pet V2 — Insights Math

This document is the **source of truth** for what the Insights feed surfaces
and how each card is computed. It complements [reports-math.md](reports-math.md):
if behavior in code contradicts this doc, fix the code or update the doc
(after discussion), never silently drift.

## 1. Card envelope

Every card returned by `GET /api/insights/feed` follows this shape:

| Field           | Type          | Notes                                                 |
|-----------------|---------------|-------------------------------------------------------|
| `type`          | string        | Stable identifier, e.g. `financial_health`            |
| `severity`      | `info`/`warn` | Only `warn` counts toward `actionable_count`          |
| `title`         | string        | Short, user-visible                                   |
| `summary`       | string        | One-liner, used for Dashboard teaser                  |
| `detail`        | string\|null  | Longer description                                    |
| `dedupe_key`    | string        | Stable across recomputes; used for persistence & UI   |
| `action_url`    | string\|null  | Route to open on click                                |
| `action_label`  | string\|null  | Button copy (defaults to a generic label)             |

The feed payload also returns `actionable_count` (count of `warn`) and
`new_count` (cards whose `first_seen_at > user.insights_last_viewed_at`).
Starting with Phase 4, `new_count` is computed from the persisted
`insights_cards.first_seen_at` column: a card is "new" exactly when it was
first stored after the viewer last visited the Insights page. Cards are
also returned with a `user_state` overlay and an `is_new` flag so the
front-end can render NEW ribbons per card without recomputing.

## 2. Card catalog (Phase 1 scope)

### `financial_health`

Severity: `info`. Inputs: [`ReportsRepository.get_financial_health_data`](../web/reports/repo.py) +
[`compute_health_score`](../web/reports/calculations.py).

Key window rules:

- `monthly_income_cents` and `monthly_expenses_cents` are both **3-month
  averages over completed months**. This makes `savings_rate` well-defined
  early in the month; previously expenses were measured as partial MTD,
  so early-month scores looked artificially great.
- `annual_income_cents` is the **real 12-month income sum** (not
  `monthly_income * 12`). DTI stays stable when a single month has a
  bonus or missing paycheck.
- `total_debt_cents` reflects **credit-card balances only**. Mortgage
  and installment loans are carried separately in `mortgage_loan_cents`;
  they surface in `advice` but never penalize the DTI component.
- `avg_monthly_expenses_cents` (6-month average) feeds only the
  emergency-fund metric, not savings-rate.
- Privacy: `viewer_user_id` filters out private transactions owned by
  other family members from every income/expense aggregate.

### `cash_flow_mom`

Severity: `warn` if current MTD net < prior MTD net, else `info`.

Compares **equal windows**:

```
current: [first_of_month, today]
prior:   [first_of_prior_month, first_of_prior_month + (today.day - 1)]
```

The prior-window end-day is clamped to the prior month's length (Feb vs
Mar edge case). Implementation: `ReportsRepository.get_cash_flow_window`.

### `top_category`

Severity: `info`. Takes `ReportsRepository.get_by_category(month, rollup="primary")`,
filters to `amount_cents > 0`, then picks the max.

Negative-total categories (refunds > spend) are excluded so the card can
never pick the "least-negative" bucket as the top spender.

### `forecast`

Severity: `info`. Count of upcoming outflow occurrences in the next 14
days from `build_forecast`.

A stream is excluded from the forecast if:

- `is_active = false`, or
- `status = 'TOMBSTONED'` (Plaid's stopped marker), or
- `direction != 'outflow'`, or
- `last_date` is missing / next occurrence falls outside the window.

### `price_changes_warn` / `price_changes_good`

Severity: `warn` for unfavorable moves (outflow + price up, inflow + price
down), `info` for favorable ones. Uses `RecurringRepository.get_price_changes`
which surfaces streams whose latest charge differs from the long-term
average by more than `PRICE_CHANGE_THRESHOLD` (10%).

## 3. Privacy model

- Every repository call used by the feed accepts `viewer_user_id`.
- `ReportsRepository.*` applies `_private_tx_filter_with_idx` so private
  transactions owned by other users are excluded from aggregates.
- `RecurringRepository.list_streams` / `get_price_changes` filter streams
  to those whose underlying account is owned by the viewer or is a
  shared account (`accounts.user_id IS NULL`). This closes the
  metadata-leak where warn cards could name a merchant from a private
  account belonging to another user.

## 3a. Persistence, caching, dismiss/snooze (Phase 4)

The feed is stateless to compute but stateful on the wire: every card
has a stable `dedupe_key` that maps 1:1 into the `insights_cards` table.

### Tables

- `insights_cards (dedupe_key PK, type, severity, title, summary, detail,
  action_url, action_label, payload jsonb, first_seen_at, last_seen_at)`
  — persists the most recent rendering for each surfaced card.
  `first_seen_at` is preserved on ON CONFLICT, so "new" survives across
  recomputations. `last_seen_at` refreshes whenever a re-compute still
  emits this `dedupe_key`; cards whose `last_seen_at` ages past
  `card_prune_days` (default 30) are garbage-collected, **unless** a user
  still has a dismiss/snooze row attached.
- `insights_card_user_state (user_id, dedupe_key, dismissed_at,
  snoozed_until, updated_at)` — per-user overlay. Hiding an alert in one
  account never hides it for another family member; this is how we keep
  alerts private the same way `insights_last_viewed_at` does.

### Cache

`get_feed_cached(viewer_user_id)` caches the computed payload in-process
for `cache_ttl_seconds` (default 300). The cache key is the viewer, so
the privacy model from §3 is preserved. Every mutation
(`dismiss`/`snooze`/`unhide`/`mark-viewed`) invalidates the viewer's
cache entry.

### Configurable thresholds

Defaults live in [`web/insights/config.py`](../web/insights/config.py)
and can be overridden at runtime by writing JSON into
`app_settings.insights_config` (e.g. `{"budget_risk_ratio": 0.8,
"forecast_window_days": 7}`). Keys not present in `DEFAULTS` are ignored,
so experimental settings never silently widen the schema.

### Endpoints

- `POST /api/insights/{dedupe_key}/dismiss` — hide permanently for this
  user.
- `POST /api/insights/{dedupe_key}/snooze` body `{until: ISO-8601}` —
  hide until `until`. The server clamps `until` to `snooze_max_days`
  (default 90) and rejects timestamps in the past.
- `POST /api/insights/{dedupe_key}/unhide` — clear both fields.
- `GET /api/insights/feed?include_hidden=true` — also returns dismissed
  / still-snoozed cards with their `user_state`, so the UI can offer
  "Unhide".

## 4. Non-goals / open questions

- **No per-account utilization card in Phase 1.** Added in Phase 3 as
  `high_utilization`.
- **No anomaly detection on individual transactions.** Requires a
  dedicated plan.
- **Monthly-payment-based DTI.** Not implemented; the current DTI excludes
  mortgages/loans from principal to achieve the same effect without
  requiring accurate minimum-payment data.

## 5. Rollout notes

Phase 1 ships as a pure math/privacy fix. Severity mixes and totals on
already-populated screens may change:

- Users who had a mortgage saw their health score penalized by ~25
  points; it recovers after this release.
- The `cash_flow_mom` card stops firing false warns during the first
  weeks of a month.
- Expense-heavy categories with refunds no longer crowd out the real
  top spender.
