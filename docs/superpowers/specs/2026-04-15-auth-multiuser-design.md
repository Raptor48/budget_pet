# Auth & Multi-User Design

**Date:** 2026-04-15  
**Status:** Approved  
**Context:** Private family budget app (Budget Pet). Not public. 2–5 users max.

---

## Goals

1. Fix existing security vulnerabilities in auth system.
2. Support multiple family member accounts with equal data access.
3. One owner (Denis) manages users via UI — no redeploy required.
4. Sessions persist across Railway restarts (survive service restarts).

## Non-Goals

- Role-based access control (all users have identical data access)
- Email verification or password reset flows
- OAuth / social login
- Audit logs per user

---

## Database Schema

Two new tables in existing PostgreSQL database.

```sql
CREATE TABLE IF NOT EXISTS users (
    id           SERIAL PRIMARY KEY,
    username     TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,         -- bcrypt, cost factor 12
    is_owner     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
    token        TEXT PRIMARY KEY,       -- secrets.token_urlsafe(32)
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    expires_at   TIMESTAMPTZ NOT NULL,   -- created_at + 30 days
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);
CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions(expires_at);
```

**Migration:** `web/auth/db_migration.py` runs `CREATE TABLE IF NOT EXISTS` at app startup via `@app.on_event("startup")`. Safe to run repeatedly.

**Bootstrap:** On first login attempt, if the `users` table is empty, the system creates an owner account using `ADMIN_LOGIN` / `ADMIN_PASSWORD` env vars. After that, those env vars are ignored for login — all auth goes through the DB.

**Expired session cleanup:** Lazy — runs on every login call (`DELETE FROM sessions WHERE expires_at < NOW()`).

---

## Backend

### New module: `web/auth/users_repo.py`

All DB operations for users and sessions. Uses `asyncpg` (consistent with finance/plaid repos).

Functions:
- `get_user_by_username(conn, username) -> User | None`
- `create_user(conn, username, password_hash, is_owner) -> User`
- `list_users(conn) -> list[UserPublic]` — no password hashes
- `delete_user(conn, user_id)` — raises if deleting last owner
- `create_session(conn, user_id, expires_days=30) -> str` — returns token
- `get_session_user(conn, token) -> User | None` — checks expires_at
- `delete_session(conn, token)`
- `cleanup_expired_sessions(conn)`

### Modified: `web/auth/routes.py`

- `POST /api/auth/login` — bcrypt verify → create DB session → set httpOnly cookie. **Token removed from response body.**
- `POST /api/auth/logout` — delete session from DB → clear cookie.
- `GET /api/auth/me` — unchanged behavior, reads from DB session.
- `POST /api/users` — create user (owner only). Body: `{username, password}`.
- `GET /api/users` — list users (owner only). Returns id, username, is_owner, created_at.
- `DELETE /api/users/{user_id}` — delete user (owner only, cannot delete self, cannot delete last owner).

### Modified: `web/auth/middleware.py`

Session lookup changes from `active_sessions` dict to `get_session_user(conn, token)`. Behavior for callers is identical.

### Security fixes (same iteration)

| Issue | Fix |
|---|---|
| Hardcoded fallback password | Remove default value from `os.getenv("ADMIN_PASSWORD", ...)`. App raises `RuntimeError` at startup if `ADMIN_LOGIN` or `ADMIN_PASSWORD` not set. |
| Token in response body + localStorage | Remove `token` field from `LoginResponse`. Frontend relies solely on httpOnly cookie. |
| `ADMIN_KEY` optional | If `ADMIN_KEY` env var not set, sync routes return `503 Service Unavailable` with message "Sync disabled: ADMIN_KEY not configured". |
| `ADMIN_KEY` as query param | Change `require_admin_key` to read from `X-Admin-Key` HTTP header using FastAPI `Header()`. |
| No rate limiting on login | Add in-memory sliding window: 5 failed attempts per IP per 60 seconds. Returns `429 Too Many Requests`. |

---

## Frontend

### Modified: `frontend/src/lib/auth.ts`

- Remove all `localStorage.setItem('auth_token', ...)` and `localStorage.getItem('auth_token')`.
- `login()` no longer stores token — relies on cookie set by server.
- `checkAuthStatus()` calls `GET /api/auth/me` with `credentials: 'include'`.
- `logout()` calls `POST /api/auth/logout` with `credentials: 'include'`.

### Modified: `frontend/src/lib/api.ts`

- Remove `Authorization: Bearer` header injection from localStorage.
- Keep `credentials: 'include'` on all requests (cookie sent automatically).

### New page: `frontend/src/app/settings/users/page.tsx`

- Visible only to owners (`user.is_owner === true`). Non-owners get 403 redirect.
- Displays user list: username, owner badge, delete button (not shown for self or if only one owner).
- "Add user" form: username + password fields → `POST /api/users`.
- Uses TanStack Query for data fetching (consistent with rest of app).

### Modified: Navigation

- Add "Users" link under Settings, conditionally rendered when `currentUser.is_owner`.

---

## Data Flow: Login

```
Browser → POST /api/auth/login {username, password}
  → middleware skips /api/auth/*
  → routes.py: get_user_by_username → bcrypt.verify
  → create_session in DB → token
  → Set-Cookie: session_token=<token>; HttpOnly; Secure; SameSite=None
  → Response: {username, is_owner}  (no token field)
Browser stores nothing — cookie managed by browser automatically
```

## Data Flow: Authenticated Request

```
Browser → GET /api/finance/... (cookie sent automatically)
  → AuthMiddleware: reads cookie → get_session_user(token)
  → If expired or not found → 401
  → If valid → request.state.user = user → proceed
```

---

## Error Handling

- Wrong password: `401 Unauthorized` — generic "Invalid credentials" (no hint which field is wrong)
- Rate limited: `429 Too Many Requests` with `Retry-After` header
- Owner-only endpoint called by non-owner: `403 Forbidden`
- Delete last owner: `400 Bad Request` — "Cannot delete the last owner account"
- Missing `ADMIN_LOGIN`/`ADMIN_PASSWORD` at startup: `RuntimeError` (app won't start)
- Missing `ADMIN_KEY` at startup: sync routes disabled with `503`

---

## Testing

- `tests/test_auth_users.py` — unit tests for `users_repo.py` (create, list, delete, session lifecycle)
- `tests/test_auth_routes.py` — integration tests: login flow, logout, rate limiting, owner-only endpoints, bootstrap flow
- Existing auth tests updated to reflect new response shape (no `token` in body)

---

## Migration Path (Production)

1. Deploy new code — migration runs at startup, creates tables.
2. First login with existing `ADMIN_LOGIN` / `ADMIN_PASSWORD` → creates owner account in DB.
3. From that point, manage users via `/settings/users`.
4. `ADMIN_LOGIN` / `ADMIN_PASSWORD` remain in env (used only for bootstrap check on empty DB).
