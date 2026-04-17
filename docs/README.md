# Budget Pet — Documentation

> **V2.0 — Plaid-First Family Budget**
> All documentation here reflects the current V2 architecture.

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

## Plaid Sandbox Testing

1. Go to Settings → Connect Bank
2. Select any bank in Plaid Link
3. Login: `user_good` / `pass_good`
4. Settings → Sync Now

## Archive

Old V1 documentation is preserved in [`archive/v1/`](./archive/v1/) for reference.
