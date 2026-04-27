# CLAUDE.md — agent orientation for budget_pet

This file is for the next AI agent (or any reader) joining the project cold.
It is intentionally short. Authoritative specs live in [`docs/`](docs/README.md);
this file points at them and captures conventions that are easy to miss.

## What is this

Family budget app. **FastAPI** backend + **Next.js** frontend + **PostgreSQL**
on Railway. **Plaid** is the source of truth for linked banks: transactions,
accounts, categories (PFC), recurring streams, liabilities, and investments.
Cash spending lives in the same `transactions` table on a per-user **Cash**
wallet account.

## Layout

```
web/                      FastAPI service (Python 3.12, asyncpg)
  main.py                 app + startup; routers under /api/*
  db.py                   shared asyncpg pool singleton
  migrations/v2_init.py   idempotent CREATE TABLE / ALTER COLUMN bootstrap
  auth/                   sessions, multi-user, ADMIN_* bootstrap
  plaid/                  Link, sync, scheduler, crypto.py
  accounts categories tags transactions recurring budgets investments
  reports insights internal_transfers app_settings audit
frontend/                 Next.js 15 + React 19 + TS strict + Tailwind
  src/app/                pages
  src/components/         UI components
  src/lib/                api client, helpers
  src/types/v2.ts         shared types (mirrors backend models)
docs/                     authoritative specs — read these
  README.md architecture.md api.md data-model.md plaid.md
  reports-math.md insights-math.md archive/v1/
bot.py services/          DEPRECATED Telegram bot — do not extend
tests/v2/                 pytest-asyncio test surface (~50 files)
pyproject.toml            ruff (E/F/W/B) + pytest config; bot.py excluded
.env.template             env-var docs (kept current)
LICENSE                   MIT
```

## Branches and Railway

The Railway project is `protective-clarity` with two environments wired to
two long-lived branches:

| Environment | Branch | What lives there |
|---|---|---|
| `production` | `main` | Real Plaid, real users. Auto-deploys on merge. |
| `demo` | `demo` | Plaid `sandbox`. Reviewer login `demo` / `demo_pass`. Updated by hand via PRs targeting `demo`. |

Day-to-day work happens on a versioned working branch: **`V2.3`** at the time
of writing. Workflow: commit to `V2.3` → PR into `main` → merge → production
deploy. The `demo` branch lags behind on purpose; sync it explicitly when
you want reviewers to see new things.

Services on Railway: `FastAPI`, `Next.js (Web UI)`, `Postgres DB`,
`telegram bot` (the last one is for the deprecated bot).

## Things that are easy to break — read before touching

### Railway env wiring

Every service that talks to Postgres MUST set `DATABASE_URL` to the
**templated reference** `${{Postgres-DB.DATABASE_URL}}`. Note the hyphen —
the service is named `Postgres DB` (with a space) and Railway references
replace spaces with hyphens. A literal `DATABASE_URL` value breaks the
moment `POSTGRES_PASSWORD` rotates and is a real foot-gun (one whole
incident in this repo's history).

When asked to rotate the Postgres password: `ALTER USER postgres WITH
PASSWORD '...'` first (so `pg_authid` matches what the templated env will
produce), then `railway variable set POSTGRES_PASSWORD=...`. Both
synchronously, not one without the other.

### Plaid access-token encryption (soft rollout)

`plaid_items.access_token_encrypted` (BYTEA, Fernet) is the live column.
Legacy `access_token TEXT` is kept NULL after backfill as a safety net —
**plan to drop it in a follow-up release** once the encrypted path is
verified in production for ~1 week. See `docs/plaid.md#access-token-encryption-at-rest`.

`web/plaid/crypto.py` is the only module that touches keys.
`PlaidRepository.save_item / get_item / get_items` decorate rows
transparently; downstream callers (scheduler, routes, webhook_config)
keep using `item["access_token"]` as plaintext.

`PLAID_ENCRYPTION_KEY` operational rules:

- Generate once with `Fernet.generate_key().decode()`.
- Store in a password manager. Losing the key = re-link every bank by
  hand (pg_authid still has the encrypted blob, but no way to read it).
- **Never rotate** without an offline decrypt-and-re-encrypt pass.

### Plaid SDK timeouts

The Plaid Python SDK is synchronous. Every call in
`web/plaid/scheduler.py` goes through `_plaid_call(fn, *args)` which is
`asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=PLAID_SDK_TIMEOUT)`
(default 90s). Without this wrapper, a hung Plaid response would freeze the
asyncio event loop and the daily sync would never recover. **Don't bypass
`_plaid_call`.**

### Source of truth for income vs expense

Single field: `transactions.transaction_class` ∈ `{income, expense,
internal_transfer, uncategorized}`. The classifier
(`web/classification/classifier.py`) runs on import + on a 7-day rescan
window. Rule order is documented in [`docs/reports-math.md`](docs/reports-math.md);
do not invent a parallel `is_income` flag in repos.

Plaid sign convention: `amount > 0 = expense`, `amount < 0 = income`.
Income is stored with negative `amount_cents` and flipped to positive in
report queries via `SUM(CASE WHEN income THEN -amount_cents ELSE 0 END)`.

### Privacy (`is_private`)

Family-app concept, not a security boundary. Every repo that reads
`transactions` accepts a `viewer_user_id` and injects
`NOT is_private OR accounts.user_id = $viewer`. Internal/startup jobs pass
`viewer_user_id=None` to bypass the filter on purpose.

## Conventions

- **asyncpg only** on the backend — no psycopg2.
- **All routes under `/api/`** — protected by `AuthMiddleware`. Public
  exceptions: `/api/auth/*`, `/healthz`.
- **PFC auto-mapping**: categories are auto-created from Plaid's
  `personal_finance_category` on first sync.
- **Splits invariant**: `SUM(transaction_splits.amount_cents) =
  parent.amount_cents`.
- **Sandbox transactions** are included in reports/budgets/CSV when
  `PLAID_ENV=sandbox` unless `REPORTS_INCLUDE_PLAID_SANDBOX=false` (see
  `web/env_flags.py`).
- **TypeScript**: `strict: true`, no `any`, no `@ts-ignore` (we cleaned
  these up — keep it that way). Lucide icons; reuse `formatMoney` from
  `frontend/src/components/accounts/helpers.ts` instead of writing a new
  `Intl.NumberFormat`.
- **Frontend toasts**: only via `notify.success/error/info` from
  `frontend/src/lib/notify.ts`. Never `window.alert`/`window.confirm`.
- **Telegram bot is deprecated.** `bot.py` and `services/` are excluded
  from `ruff` and not in scope. Don't extend them.

## Common commands

```bash
# Backend
PYTHONPATH=. uvicorn web.main:app --reload --reload-dir web --port 8000
ruff check web/                       # lint (E/F/W/B; UP/I001 deferred)
pytest tests/v2 tests/test_auth_routes.py tests/test_auth_users.py -q

# Frontend
cd frontend && npm install
npm run dev                           # Turbopack dev server
npx tsc --noEmit                      # type check
npx eslint .                          # lint (no errors expected; 2 <img> warnings)
npm run build

# Railway (link first: railway link --project protective-clarity --environment production)
railway service status --all
railway logs --lines 100
railway variables --json              # for inspecting names; values are guarded
railway redeploy --service FastAPI -y
railway ssh                           # interactive shell into a linked service
```

## Open follow-ups (for the next session)

1. **Drop legacy column** `plaid_items.access_token TEXT`. Wait ~1 week
   from 2026-04-25 to confirm encrypted path is stable, then a one-line
   migration: `ALTER TABLE plaid_items DROP COLUMN access_token`.
2. **Bump Next.js** to 15.5.x (or current) to clear the remaining 1 high
   + 1 moderate npm-audit advisory. Run `npm run build` + manual smoke
   test before shipping.
3. **Refactor mega-file** `frontend/src/app/transactions/page.tsx`
   (~2200 LOC) into `_components/` per concern.
4. **Consolidate `formatMoney`** — `Intl.NumberFormat` is duplicated in
   ~12 places; the canonical helper is in
   `frontend/src/components/accounts/helpers.ts`.
5. **CI**: add `.github/workflows/ci.yml` that runs `ruff check`,
   `pytest`, `tsc --noEmit`, `npm run lint`, `npm run build` on PRs.
6. **Optional `git filter-repo`** to strip the leaked `.env` from history
   (already-rotated secrets, not a security blocker — purely cosmetic).

## Recent context (2026-04-25)

Big security + hygiene cleanup landed via [PR #5](https://github.com/Raptor48/budget_pet/pull/5):

- Untracked `.env`/`.env.local`; rotated `PLAID_SECRET`,
  `ADMIN_PASSWORD`, `POSTGRES_PASSWORD`. New
  `PLAID_ENCRYPTION_KEY` set on Railway production; backfill encrypted
  the existing access tokens at rest.
- Wrapped Plaid SDK calls in `_plaid_call` with timeout.
- Added `LICENSE` (MIT), `pyproject.toml` (ruff + pytest), 144
  unused-import autofixes.
- Compact redesign of the Transaction details modal
  (`frontend/src/app/transactions/page.tsx`).
- Branch hygiene: deleted `V2.1`, `V2.2`, `v2.0`; renamed `V2.2 → V2.3`;
  kept `main`, `V2.3`, `demo`.

## Transaction details redesign pass (V2.3 working branch)

Landed on `V2.3` after PR #5; visible to reviewers when merged via PRs
into `main`. Notable changes touching `frontend/src/app/transactions/`:

- Modal: dedup'd PFC chip, moved Plaid category + bank descriptor into
  the **More details** disclosure, replaced the always-visible confidence
  pill with a single amber warning that fires only when Plaid confidence
  is `LOW`/`UNKNOWN` *and* the row is still uncategorized. Save button is
  now disabled-until-dirty (snapshot of initial note + category) and
  flips variant when there are real changes.
- Channel-icon palette muted; the only spot of color in the modal is a
  **left-border accent painted with the assigned `category.color`** so
  the meaningful classification is what the eye lands on.
- `MerchantAvatar` fallback: 8-color **deterministic gradient** keyed off
  `merchant_entity_id || displayName(tx)` (with non-alphanumerics
  stripped) so two rows of the same merchant always pick the same color.
  Plaid logos still win when present.
- Footer line: `Synced from Plaid · {N} ago` (or `Created · …` for cash /
  manual rows) using `transaction.updated_at` via `formatDistanceToNow`.
- Detail dialog uses `placeholderData` from the `["transactions", …]`
  query cache, so the modal renders **instantly** with the row already
  in view; the freshness GET runs in the background. Hides Railway
  cold-start latency without staleness — list invalidations on mutations
  keep the cache honest.
- `<img>` → `next/image` for every Plaid icon (merchant + PFC),
  `images.remotePatterns` allowlists `plaid-merchant-logos.plaid.com`
  and `plaid-category-icons.plaid.com`. Tagged `unoptimized` because
  Plaid icons are 100×100 PNGs from a global CDN — the optimizer would
  only add a hop. Institution logos (account-tile, flip-card) remain
  `<img>` on purpose: they're stored as base64 data URLs in the DB.

Audit reports in earlier sessions flagged several other items (broad
`except Exception`, two-pattern repository DI, no Alembic migrations) —
all real but deliberately deferred. Pick one if you have a slow day.
