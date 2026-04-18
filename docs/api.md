# Budget Pet V2 — API Reference

All endpoints require authentication (session cookie or Authorization: Bearer header).
Base URL: configured in NEXT_PUBLIC_API_URL.

### Transaction privacy (`is_private`)

Any transaction (cash, Plaid, manual) can be marked `is_private: true`. In that
case the row is **visible only to the account owner**; all other family
members get a filtered response where the transaction is omitted entirely.
**All signed-in users** otherwise see the same family-wide transaction list,
CSV export, and date-range bounds (optional `user_id` query filter narrows to
one member’s accounts in the UI). The filter uses
`session.user.id` as the viewer; calls without an authenticated session
(internal/startup only) bypass the filter.

## Accounts

| Method | Path | Description |
|---|---|---|
| GET | /api/accounts | List accounts (active_only=true default); each row includes `is_cash_wallet` when applicable |
| GET | /api/accounts/cash-wallet | Ensure and return the per-user **Cash** wallet (no Plaid link) |
| POST | /api/accounts | Create manual account |
| GET | /api/accounts/{id} | Get account |
| PATCH | /api/accounts/{id} | Update account; **`current_balance_cents` allowed only** on the designated Cash wallet (422 otherwise) |
| DELETE | /api/accounts/{id} | Soft-delete account |

## Categories

Each category has `source`: **`plaid_pfc`** (created when syncing Plaid transactions / streams) or **`custom`** (created via POST). Only **`custom`** rows can be deleted. All rows may be PATCHed for display `name` / `color` / `icon`.

| Method | Path | Description |
|---|---|---|
| GET | /api/categories | List all categories. Response rows include `parent_id` (nullable self-FK) so the frontend can render a two-level hierarchy (primary bucket → detailed subcategories). |
| POST | /api/categories | Create **custom** category (`name`, optional `color`, `icon`; no Plaid PFC fields) |
| GET | /api/categories/{id} | Get category |
| PATCH | /api/categories/{id} | Update `name`, `color`, `icon` |
| DELETE | /api/categories/{id} | Delete **custom** only (`404` if Plaid-derived or missing) |

## Tags

| Method | Path | Description |
|---|---|---|
| GET | /api/tags | List all tags |
| POST | /api/tags | Create tag |
| PATCH | /api/tags/{id} | Update tag |
| DELETE | /api/tags/{id} | Delete tag |

> Note: the V2 frontend currently only uses `GET /api/tags`; the mutating
> endpoints remain available for future UI/automation but have no active
> callers.

## Merchant category rules

Rules are **family-wide** (one row per `merchant_key`). Import applies them after PFC resolution. Bulk **apply-existing** only runs `UPDATE transactions SET category_id = …` for matching Plaid rows (`source` in `plaid`, `plaid_sandbox`); rows with **splits**, **custom** categories, or (for name-only rules) a non-empty **merchant_entity_id** are skipped. **`is_private` is not changed.** Re-running apply when nothing is eligible yields `updated_count: 0`.

Matching SQL coalesces `NULLIF(merchant_name, '')` onto `transactions.display_title`, so a rule created for a transaction that has no Plaid merchant (ACH / checks / bill pays — e.g. "Pmts Sec: Ind") still finds every occurrence. See `docs/plaid.md` and `docs/data-model.md#merchant_category_rules` for key-building priority.

| Method | Path | Description |
|---|---|---|
| GET | /api/merchant-rules | List rules; each row includes `display_label` (human-readable) and internal `merchant_key` (`name:…` or `eid:…`) |
| POST | /api/merchant-rules | Upsert rule; body: `category_id` and **one of** `merchant_entity_id`, `merchant_name`, `merchant_label`. `merchant_label` is the fallback used for transactions without a Plaid merchant — typically the transaction's `display_title`. |
| POST | /api/merchant-rules/preview | Read-only counts. Three body shapes: (a) `rule_id` — preview an existing rule, (b) `category_id` + merchant identifier(s) — full draft preview (`eligible_count`, `skipped_*`, `sample_merchant_names`), (c) merchant identifier(s) **without** `category_id` — lightweight `match_count` preview used by the UI before a category is picked. Missing buckets are returned as `null`. |
| POST | /api/merchant-rules/{id}/apply-existing | Apply saved rule to existing transactions (only `category_id` + `updated_at` on `transactions`; idempotent). |
| DELETE | /api/merchant-rules/{id} | Delete rule |

## Transactions

| Method | Path | Description |
|---|---|---|
| GET | /api/transactions | List transactions (filters: month, account_id, category_id, tag_id, search, channel, pending_only, optional `user_id` for one member’s accounts, limit, offset). Family-wide by default; `is_private` rows owned by others are omitted. |
| GET | /api/transactions/date-range | Earliest and latest transaction dates visible to the caller (`{ min_month, max_month, earliest, latest }`). Used by the shared month/year picker to bound year and month options. Same auth + privacy + sandbox filters as `GET /api/transactions`. |
| POST | /api/transactions | Create **cash** transaction on the user's Cash wallet (`source=cash`); body: `amount_cents`, `date`, `name`, optional `category_id`, `authorized_date`, `merchant_name`, `user_note`. Server sets `payment_channel=other`, `currency=USD`, `is_pending=false`. |
| GET | /api/transactions/{id} | Get transaction with tags and splits (returns 404 when the row is `is_private` and the caller is not the owner) |
| PATCH | /api/transactions/{id} | Update `category_id`, `user_note`, `merchant_name`, `is_private` |
| DELETE | /api/transactions/{id} | Delete non-Plaid rows (`cash`, `manual`, etc.); reverses Cash wallet balance for `source=cash` |
| POST | /api/transactions/{id}/tags/{tag_id} | Add tag |
| DELETE | /api/transactions/{id}/tags/{tag_id} | Remove tag |
| GET | /api/transactions/{id}/splits | Get splits |
| POST | /api/transactions/{id}/splits | Replace splits (validates SUM invariant) |
| DELETE | /api/transactions/{id}/splits | Clear all splits |
| GET | /api/transactions/export | CSV export (same filters as list); **`plaid_sandbox` rows follow `reports_include_plaid_sandbox()`** (included when `PLAID_ENV=sandbox` unless `REPORTS_INCLUDE_PLAID_SANDBOX=false`; production defaults to exclude) |

## Recurring Streams

| Method | Path | Description |
|---|---|---|
| GET | /api/recurring | List streams (`direction=inflow\|outflow`, `active_only`). Each row is enriched with `account_name`, `account_mask`, `owner_username` (joined from the owning account/user), `primary_category_id`/`primary_category_name`/`primary_category_color` (rolled up via `categories.parent_id`), and `display_title` (normalized description via `web/transactions/display.py::normalize_transaction_title`). |
| GET | /api/recurring/price-changes | Streams whose last charge diverges from the long-term average by more than 10%. The `price_change_pct` field is **signed** (positive = more expensive, negative = cheaper); the UI interprets the sign against `direction` to show good-news / heads-up coloring. |
| GET | /api/recurring/{id} | Get stream |
| PATCH | /api/recurring/{id} | Update user_label, category_id |
| POST | /api/recurring | Create a **manual** recurring stream (same table as Plaid); `plaid_stream_id` is synthetic `manual:{uuid}`; excluded from Plaid upsert |

## Budgets

| Method | Path | Description |
|---|---|---|
| GET | /api/budgets | List budgets (optional month filter) |
| POST | /api/budgets | Create budget (`category_id` + `month` + `budget_cents`). Rejects (`409 Conflict`) if the target conflicts with an existing budget in the category hierarchy for the same month — i.e. a child budget when a parent budget already exists, or a parent budget when any of its children already has a budget. |
| PATCH | /api/budgets/{id} | Update budget_cents |
| DELETE | /api/budgets/{id} | Delete budget |
| GET | /api/budgets/progress | Budget vs actual for month (split-aware). Parent-level budgets roll up actuals from the parent row and all of its detailed children; child-level budgets use only their exact `category_id`. |

## Investments (stub)

The `investments` namespace is reserved for Plaid's `investments` product.
The product is disabled by default and only activated when
`PLAID_ENABLE_INVESTMENTS=true` (see `docs/plaid.md`). The endpoint below is
kept as a stub so the frontend/tests don't break while we wait for Plaid
production approval; it returns an empty list when the product is off.

| Method | Path | Description |
|---|---|---|
| GET | /api/investments/holdings | List holdings (optional account_id filter) |

## Reports

All report endpoints that aggregate transactions respect the `is_private`
filter: private rows owned by someone else are dropped before aggregation,
so the monthly totals never reveal a gift someone else is planning.

| Method | Path | Description |
|---|---|---|
| GET | /api/reports/cash-flow | Income vs expenses for a month (privacy-aware) |
| GET | /api/reports/cash-flow/history | Last N months (default 12) |
| GET | /api/reports/by-category | Spending by category for month, split-aware (privacy-aware). Query params: `rollup=primary\|detailed` (default `primary` → rolls detailed PFC children into their parent bucket, returns ~10-15 slices, `bucket_key='p:<id>'`, plus `children_count`) and `parent_category_id` (used with `rollup=detailed` to scope the response to children of that primary bucket — powers the Reports "Focus mode" drilldown). |
| GET | /api/reports/by-tag | Spending by tag (optional month + tag_id filter) |
| GET | /api/reports/merchants | Top N merchants by spend |
| GET | /api/reports/net-worth | Current net worth snapshot |
| GET | /api/reports/net-worth/history | Historical snapshots (default 12 months) |
| GET | /api/reports/forecast | Cash flow forecast for next N days (30/60/90) |
| GET | /api/reports/financial-health | Health score 0–100 with metrics (privacy-aware) |

## Insights

| Method | Path | Description |
|---|---|---|
| GET | /api/insights/feed | Aggregated insight cards from existing reports (partial failures degrade per-card, not whole response). Respects the `is_private` filter via the session user. |
| POST | /api/insights/mark-viewed | Store `insights_last_viewed_at` in `user_preferences` (cross-device “seen” baseline for teaser) |

## Plaid

| Method | Path | Description |
|---|---|---|
| POST | /api/plaid/link-token | Create Plaid Link token |
| POST | /api/plaid/exchange-token | Exchange public_token for access_token |
| GET | /api/plaid/items | List connected bank items |
| GET | /api/plaid/items/{item_id}/data-summary | Counts of accounts and Plaid-sourced transactions tied to the item; used by the UI to warn before destructive delete + purge. |
| DELETE | /api/plaid/items/{item_id} | Disconnect a bank. `?purge=true` also deletes accounts, Plaid-sourced transactions, recurring streams and investment holdings for this item. Default (`?purge=false`) keeps imported data for historical reports, but reconnecting the same bank will create duplicate rows because Plaid issues new `item_id` / `account_id` values on every re-link. Cash/manual transactions are never removed. |
| POST | /api/plaid/items/{item_id}/reset-cursor | Reset sync cursor |
| POST | /api/plaid/sync | Trigger manual sync for all items |
| GET | /api/plaid/sync/log | Last 50 sync log entries |
| POST | /api/plaid/webhook | Plaid webhooks (HTTPS); verifies Plaid JWT; handles `ITEM_LOGIN_REQUIRED`, `SYNC_UPDATES_AVAILABLE` |
| DELETE | /api/plaid/sandbox-data | **Sandbox only:** delete all rows tied to `source=plaid_sandbox` (transactions, accounts, recurring, net worth snapshots, Plaid items). Preserves manual/cash data, categories, tags, budgets. |

## Auth

| Method | Path | Description |
|---|---|---|
| POST | /api/auth/login | Login (returns session cookie + token) |
| POST | /api/auth/logout | Logout (clears cookie) |
| GET | /api/auth/me | Current user info |
| GET | /api/auth/status | Auth status check |
| GET | /api/auth/members | List family members (`id`, `username`) for attribution UI |
| GET | /api/auth/users | List users (owner only) |
| POST | /api/auth/users | Create user (owner only) |
| DELETE | /api/auth/users/{id} | Delete user (owner only) |

## App settings

Every authenticated family member can read and update application-wide
settings. Two settings are currently stored here:

1. **Plaid autosync schedule** — the change takes effect live (no redeploy)
   because `PATCH /api/settings/app` reconciles the APScheduler cron job via
   `web.plaid.scheduler.apply_autosync_config`.
2. **Webhooks toggle** — when flipped, `PATCH` calls Plaid's
   `/item/webhook/update` for every linked item (via
   `web.plaid.webhook_config.reconcile_item_webhooks`). Clearing the URL at
   Plaid is what actually stops the $0.10 Balance calls that webhooks trigger;
   ignoring them locally would not change the bill. New Link tokens and
   freshly exchanged items also respect the flag so reconnecting a bank
   never silently re-opts the family back into paid webhooks.

| Method | Path | Description |
|---|---|---|
| GET | /api/settings/app | Current `{ frequency, hour_utc, minute_utc, webhooks_enabled, webhook_url_configured, updated_at, updated_by_username, next_run_at, webhook_reconcile }`. `frequency` is one of `off` / `daily` / `weekly` / `semimonthly` / `monthly` — anchor days are fixed (`weekly` = Sunday, `semimonthly` = 1st + 15th, `monthly` = 1st). `next_run_at` is null when `frequency === "off"`. `webhook_url_configured` mirrors the `PLAID_WEBHOOK_URL` env var — when false, the UI must prevent re-enabling webhooks. `webhook_reconcile` is null on GET. |
| PATCH | /api/settings/app | Partial update. Any of `frequency` (enum above), `hour_utc` (0-23), `minute_utc` (0-59), `webhooks_enabled`. Reschedules the APScheduler job immediately (adds, reschedules, or removes it depending on the new frequency), pushes webhook changes to every Plaid item when `webhooks_enabled` flipped, and writes a `settings.autosync_updated` row to `audit_log` (the metadata includes both the frequency and the reconcile summary). Responds with the same shape as GET plus a populated `webhook_reconcile` object `{ updated, failed, total, errors }` when the flag flipped. |

## Audit log

Append-only activity feed powering Settings → Log. Entries are written by the
non-throwing helper `web.audit.record(...)` from auth, Plaid, settings and
scheduler call sites.

| Method | Path | Description |
|---|---|---|
| GET | /api/audit | Newest-first paginated feed. Query: `limit` (1-200, default 50), `before_id` (cursor — pass the last id from the previous page), `event_type` (exact match), `category` (namespace — e.g. `plaid` → matches `plaid.*`). Returns `{ entries: AuditEntry[], next_before_id }`. |
| GET | /api/audit/event-types | Distinct `event_type` values currently in the table (useful to populate a filter dropdown). |

`AuditEntry` fields: `id`, `created_at`, `actor_user_id`, `actor_username`,
`event_type`, `source` (`manual`|`scheduler`|`webhook`|`system`),
`target_kind`, `target_id`, `metadata` (JSON), `request_ip`.

## Health

| Method | Path | Description |
|---|---|---|
| GET | /healthz | Health check |
