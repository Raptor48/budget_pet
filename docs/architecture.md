# Budget Pet V2 — Architecture

## Overview

V2 is centered on Plaid API for linked institutions (transactions, accounts, categories, recurring). Offline **cash** spending uses the same `transactions` table with `source=cash` on a per-user **Cash** wallet account (see `docs/data-model.md`).

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, Uvicorn, asyncpg |
| Frontend | Next.js 15, React 19, TypeScript 5, Tailwind CSS 4, TanStack Query |
| Database | PostgreSQL (Railway) |
| Plaid | plaid-python 39+, products: transactions, liabilities, investments, recurring_transactions |
| Hosting | Railway (FastAPI, Next.js, Postgres services) |

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
├── recurring/           — /api/recurring + price change detector
├── budgets/             — /api/budgets + progress calculation
├── investments/         — /api/investments/holdings
└── reports/             — /api/reports/* (cash flow, net worth, forecast, health)
```

## Data Flow

```
Plaid API
    │
    ▼
plaid/scheduler.py (daily 03:00 + manual POST /api/plaid/sync)
    │
    ├── accounts/balance/get  ──→ accounts table (provision + update balances)
    ├── transactions/sync     ──→ transactions table (upsert by plaid_transaction_id)
    │                              └── categories (auto-resolve via PFC)
    ├── liabilities/get       ──→ accounts table (APR, min_payment, overdue)
    ├── recurring/get         ──→ recurring_streams table
    ├── investments/holdings  ──→ securities + investment_holdings tables
    └── snapshot_net_worth()  ──→ net_worth_snapshots table
```

## Authentication

- DB-backed sessions (users + sessions tables)
- Owner accounts manage family members via /api/auth/users
- Emergency bypass via ADMIN_LOGIN / ADMIN_PASSWORD env vars
- Cookie auth + Authorization: Bearer fallback for cross-origin

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
