# Budget Pet — Documentation

> **Plaid-First Family Budget.** Everything here describes the live FastAPI +
> Next.js + Postgres surface. Working branch is currently `V2.3`; production
> deploys from `main`, the public-facing demo from `demo` (Plaid sandbox).
> See [`../CLAUDE.md`](../CLAUDE.md) for an agent-friendly orientation.

## Documents

| File | Description |
|------|-------------|
| [architecture.md](./architecture.md) | System architecture, stack, module structure, data flow, Railway envs, encryption-at-rest, Plaid SDK timeouts, in-process Telegram bot |
| [api.md](./api.md) | All API endpoints reference |
| [data-model.md](./data-model.md) | Database schema — all V2 tables with field descriptions (incl. `plaid_items.access_token_encrypted` and the bot v1 tables) |
| [plaid.md](./plaid.md) | Plaid integration: products, sync flow, field mapping, sandbox, access-token encryption |
| [bot.md](./bot.md) | Telegram bot — surface, architecture, config, webhook setup, DB tables |
| [reports-math.md](./reports-math.md) | Source of truth for income / expense / internal_transfer classification |
| [insights-math.md](./insights-math.md) | Insights feed math |
| [categorization-precedence.md](./categorization-precedence.md) | Single source of truth for which mechanism wins when PFC mapping, merchant rules, manual edits, splits, classifier, aliases, and tags collide |

## Quick Start (local)

```bash
# Backend (port 8000)
uvicorn web.main:app --reload

# Frontend (port 3000)
cd frontend && npm run dev
```

DB migrations and category seeding run automatically on startup.

Required env vars (see `.env.template`):

- `DATABASE_URL` — Postgres connection string. **On Railway** it must be the
  templated reference `${{Postgres-DB.DATABASE_URL}}` (note the hyphen — the
  service is named `Postgres DB` and references replace spaces with hyphens).
  A literal value breaks the next time the Postgres password rotates.
- `ADMIN_LOGIN` / `ADMIN_PASSWORD` — primary owner account bootstrapped on
  startup (plain ASCII login).
- `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` — Plaid credentials (see
  `docs/plaid.md`).
- `PLAID_ENCRYPTION_KEY` — Fernet key for access-token encryption at rest.
  Generate once with `Fernet.generate_key()`, store in your password manager,
  **never rotate** (see `docs/plaid.md#access-token-encryption-at-rest`). The
  app boots without it (plaintext fallback) but logs a CRITICAL warning.
- `PLAID_SDK_TIMEOUT` *(optional, default 90s)* — per-call timeout for
  synchronous Plaid SDK requests; daily sync wraps every call in
  `asyncio.wait_for` so a hung Plaid response cannot freeze the scheduler.
- `CORS_ORIGINS` — comma-separated browser origins for the Next.js
  frontend (e.g. `https://your-app.up.railway.app`). No production host
  is hardcoded.

## Installable app (PWA)

The frontend ships a Web App Manifest and Apple touch icons, so it can be
added to the home screen on iOS / iPadOS / Android, and installed as a
standalone window on macOS (Safari → Share → Add to Dock) and Windows
(Edge/Chrome → Install app). Icons live in `frontend/public/` and
`frontend/src/app/` and are referenced from
`frontend/src/app/manifest.ts`.

## Plaid Sandbox Testing

1. Go to Settings → Connect Bank
2. Select any bank in Plaid Link
3. Login: `user_good` / `pass_good`
4. Settings → Sync Now

## Archive

Old V1 documentation is preserved in [`archive/v1/`](./archive/v1/) for reference.
