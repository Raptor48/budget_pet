# Budget Pet — Documentation

> **V2.1 — Plaid-First Family Budget**
> All documentation here reflects the current V2.1 architecture (Plaid as the
> source of truth + offline cash wallet + per-row `is_private` + PWA shell).

## Documents

| File | Description |
|------|-------------|
| [architecture.md](./architecture.md) | System architecture, stack, module structure, data flow |
| [api.md](./api.md) | All API endpoints reference |
| [data-model.md](./data-model.md) | Database schema — all V2 tables with field descriptions |
| [plaid.md](./plaid.md) | Plaid integration: products, sync flow, field mapping, sandbox |

## Quick Start (local)

```bash
# Backend (port 8000)
uvicorn web.main:app --reload

# Frontend (port 3000)
cd frontend && npm run dev
```

DB migrations and category seeding run automatically on startup.

Required env vars (see `.env.template`):

- `DATABASE_URL` — Railway Postgres URL.
- `ADMIN_LOGIN` / `ADMIN_PASSWORD` — primary owner account bootstrapped on
  startup (plain ASCII login).
- `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` — Plaid credentials (see
  `docs/plaid.md`).
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
