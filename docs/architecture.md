# Budget Pet V2 — Architecture

## Overview

V2 is centered on Plaid API for linked institutions (transactions, accounts, categories, recurring). Offline **cash** spending uses the same `transactions` table with `source=cash` on a per-user **Cash** wallet account (see `docs/data-model.md`).

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn, asyncpg |
| Frontend | Next.js 15, React 19, TypeScript 5, Tailwind CSS 4, TanStack Query |
| Database | PostgreSQL (Railway) |
| Plaid | plaid-python 39+, products: transactions, liabilities, investments, recurring_transactions |
| Hosting | Railway (FastAPI, Next.js, Postgres services) |

## Railway environments and deploy branches

The Railway project (`protective-clarity`) runs two environments off the same
codebase but different branches:

| Environment | Source branch | Purpose |
|---|---|---|
| `production` | `main` | Real Plaid data, real users. Auto-deploys on merge to `main`. |
| `demo` | `demo` | Portfolio-facing sandbox. Plaid `sandbox` mode, login `demo` / `demo_pass`. Updated by hand via PRs targeting `demo`. |

Day-to-day work happens on a versioned working branch (currently `V2.3`); PRs
land on `main`, which triggers the production deploy. The `demo` branch lags
behind on purpose so reviewers see a stable surface.

**Cross-service env wiring on Railway:** every service that talks to Postgres
must reference the templated value
`${{Postgres-DB.DATABASE_URL}}` (note the hyphen — the service name is
`Postgres DB`, references replace spaces with hyphens). A literal
`DATABASE_URL` becomes a foot-gun the moment `POSTGRES_PASSWORD` rotates: the
templated form auto-rebuilds, a literal does not.

## Module Structure

```
web/
├── main.py              — FastAPI app, startup, router registration
├── db.py                — Shared asyncpg pool singleton
├── migrations/
│   └── v2_init.py       — CREATE TABLE IF NOT EXISTS for all V2 tables
├── auth/                — DB-backed sessions, multi-user, rate limiting
├── plaid/               — Plaid Link, sync, scheduler
│   ├── client.py        — Plaid API wrappers (transactions, liabilities, investments, recurring)
│   ├── repo.py          — PlaidRepository: items, sync log, transaction import
│   └── scheduler.py     — APScheduler daily sync (03:00)
├── accounts/            — /api/accounts CRUD
├── transactions/        — /api/transactions CRUD + splits + CSV export
├── categories/          — /api/categories CRUD + PFC auto-mapping
├── tags/                — /api/tags CRUD + transaction-tag linking
├── recurring/           — /api/recurring + price change detector + bulk lifecycle (pause/cancel/snooze)
├── budgets/             — /api/budgets + progress calculation
├── investments/         — /api/investments/holdings
├── reports/             — /api/reports/* (cash flow, net worth, forecast, health)
├── app_settings/        — /api/settings/app (autosync schedule); singleton app_settings table
└── audit/               — /api/audit feed + non-throwing `record()` helper (audit_log table)
```

## Data Flow

```
Plaid API
    │
    ▼
plaid/scheduler.py (daily @ app_settings.autosync_hour_utc:minute_utc + manual POST /api/plaid/sync)
    │
    ├── accounts/balance/get  ──→ accounts table (provision + update balances)
    ├── transactions/sync     ──→ transactions table (upsert by plaid_transaction_id)
    │                              └── categories (auto-resolve via PFC)
    ├── liabilities/get       ──→ accounts table (APR, min_payment, overdue)
    ├── recurring/get         ──→ recurring_streams table
    ├── investments/holdings  ──→ securities + investment_holdings tables
    └── snapshot_net_worth()  ──→ net_worth_snapshots table
```

## Autosync scheduler

- Backed by APScheduler's `AsyncIOScheduler` pinned to UTC.
- Registered coroutine: `web.plaid.scheduler._scheduled_sync` (a coroutine
  function — APScheduler's `AsyncIOExecutor` awaits it directly on the main
  event loop). Pre-V2.1 the callable was a sync wrapper that submitted a
  task on a worker thread; that thread had no running loop so
  `asyncio.get_event_loop()` raised and the daily sync silently never ran.
  Keep the registered job async.
- Schedule source: the singleton row in `app_settings`. Loaded once on
  startup (`start_scheduler` → `_load_autosync_config`) and reconciled live
  by `PATCH /api/settings/app` via `apply_autosync_config(...)` — the UI
  does not need a redeploy to change cadence, time, or flip it off.
- Cadence is picked from `{off, daily, weekly, semimonthly, monthly}` with
  fixed anchor days (see `docs/plaid.md#autosync-schedule--plaid-rate-limits`).
  The mapping to `CronTrigger` kwargs lives in
  `web.plaid.scheduler._FREQUENCY_CRON_KWARGS` so the UI never has to pick
  a day-of-week or day-of-month.
- Each scheduled run writes a summary row to `audit_log` with
  `event_type = plaid.sync_scheduled` / `source = scheduler` so Settings →
  Log always shows whether the nightly job fired, even when there were no
  new transactions.

## Webhooks toggle

`app_settings.webhooks_enabled` gates every Plaid webhook touchpoint so a
family deployment can trade instant transaction notifications for a lower
Plaid bill (the `/accounts/balance/get` calls triggered by
`SYNC_UPDATES_AVAILABLE` are the main variable cost). `PATCH
/api/settings/app` owns the state machine:

1. Persist the new flag in `app_settings`.
2. If the flag changed, call
   `web.plaid.webhook_config.reconcile_item_webhooks(...)` which iterates
   `plaid_items` and sends either `PLAID_WEBHOOK_URL` or `""` to Plaid's
   `/item/webhook/update` endpoint. The response summary (`updated / failed /
   errors`) is returned on the PATCH and embedded in the audit row so the
   Log tab shows any Plaid-side failures.
3. `POST /api/plaid/webhook` early-returns when disabled, so stale
   registrations during the transition window don't schedule a debounced
   sync.
4. `POST /api/plaid/link-token` passes an explicit empty-string override to
   `create_link_token` when disabled, preventing fresh links from silently
   re-registering a webhook.

## Audit log

`web.audit.record(event_type, *, source, request=None, actor=None,
target_kind=None, target_id=None, metadata=None)` is the single entry point
for audit writes. Always non-throwing — insert failures are logged and
swallowed so audit never breaks product flows. Called from auth/login,
auth/logout (+ failures), Plaid item connect/remove/reset-cursor/sandbox
wipe, manual + scheduled Plaid sync, and `settings.autosync_updated`.
Writes go to the `audit_log` table (see `docs/data-model.md`).

## Authentication

- DB-backed sessions (users + sessions tables)
- Owner accounts manage family members via /api/auth/users
- Emergency bypass via ADMIN_LOGIN / ADMIN_PASSWORD env vars
- Cookie auth + Authorization: Bearer fallback for cross-origin

## Plaid access token encryption at rest

Plaid `access_token`s are stored as Fernet ciphertext in
`plaid_items.access_token_encrypted` (BYTEA). The legacy plain
`plaid_items.access_token` column is kept as NULL after backfill — it will be
dropped in a follow-up release once the encrypted path is verified in
production.

- `web/plaid/crypto.py` is the only module that touches keys; `PlaidRepository`
  decorates rows transparently, so `scheduler.py`, `routes.py`, and
  `webhook_config.py` keep using `item["access_token"]` as plaintext.
- A one-shot, idempotent backfill runs on every startup from
  `PlaidRepository.init_tables` and only encrypts rows where the encrypted
  column is NULL.
- **Soft rollout:** without `PLAID_ENCRYPTION_KEY`, the repo falls back to
  plaintext (and logs one CRITICAL line via `warn_if_missing_once`) so deploys
  before the env var is set still boot. With the key set, all writes encrypt
  and existing rows are backfilled on the first boot.
- **Operational rule:** generate the key once with
  `Fernet.generate_key()`, store it in your password manager, and
  **never rotate it**. A lost key means every linked Plaid item must be
  re-linked from the UI.

## Plaid SDK call timeouts

The Plaid Python SDK is synchronous (blocks a thread on HTTP). Every call
goes through `web.plaid.scheduler._plaid_call`, which wraps
`asyncio.to_thread` in `asyncio.wait_for(timeout=PLAID_SDK_TIMEOUT)` (default
90s, override via env). Without this, a hung Plaid response would freeze
the asyncio event loop and the daily sync would never run again.

## Key Conventions

- **asyncpg only** — no psycopg2
- **All routes under /api/** — protected by AuthMiddleware
- **PFC auto-mapping** — categories auto-created on first sync from personal_finance_category
- **Split transactions** — invariant: SUM(splits.amount_cents) = parent.amount_cents
- **plaid_sandbox source** — excluded from reports/budgets/CSV when `reports_include_plaid_sandbox()` is false; **by default included** if `PLAID_ENV=sandbox`, or force with `REPORTS_INCLUDE_PLAID_SANDBOX=true` (see `web/env_flags.py`)

## Privacy model (`is_private`)

Budget Pet is a family app; it is not a security boundary against outside
attackers. `is_private` exists so family members can hide a particular
spend (e.g. a gift) from each other *in the UI and in aggregates*.

- Storage: a boolean column on `transactions` + sparse index (see
  `docs/data-model.md`).
- Enforcement: every repo that reads `transactions` accepts a
  `viewer_user_id` argument and injects a `NOT is_private OR accounts.user_id = $viewer_id`
  filter. The router layer takes the viewer id from
  `request.state.user["id"]`.
- Scope: applies to list/detail, CSV export, `reports/*`, `insights/feed`
  and anything derived from them (financial health score, category donut,
  cash-flow aggregates). Does **not** apply to per-account balances — a
  private row still updates the wallet's running balance.
- Transaction **reads** are family-wide: any logged-in member can list or
  open another member’s non-private transactions. **Writes** (PATCH, DELETE,
  tags, splits) still require owning the transaction’s account (non-owners
  cannot edit someone else’s rows).
- Internal / startup jobs call the repos with `viewer_user_id=None`, which
  bypasses the filter by design.

## PWA

The Next.js app is installable on iOS / iPadOS / macOS / Android / Windows.

- Manifest is generated dynamically by `frontend/src/app/manifest.ts`.
- Icons: `frontend/public/icon-192.png` (`any`), `public/icon.png` (512,
  `any`), `public/icon-maskable.png` (512, `maskable` with safe-zone
  padding) + `frontend/src/app/apple-icon.png` picked up by Next.js.
- `appleWebApp` metadata + `theme-color` for light/dark sit in
  `frontend/src/app/layout.tsx`.
- A service worker for offline mode is intentionally out of scope for V2.1.

## Frontend UX conventions

- Toasts: `sonner`'s `<Toaster richColors />` is mounted in
  `frontend/src/app/layout.tsx`. Wrap through `notify.success/error/info`
  in `frontend/src/lib/notify.ts`; set `onError: onMutationError(...)` on
  every React Query mutation so backend errors never disappear silently.
- Confirm dialogs: `confirm(...)` from `lib/notify` returns a promise
  resolved by the single `<ConfirmDialogHost />` in the root layout. Never
  use `window.alert` / `window.confirm` directly.
- Loading states: prefer skeleton rectangles (`components/ui/skeleton.tsx`)
  over spinners for initial data loads so the page shape is preserved.
- Empty states: cards with dashed borders + CTA buttons are used in
  `insights` and `reports` when there's nothing to show.
