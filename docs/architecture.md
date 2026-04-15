# Архитектура

## Схема компонентов

```
┌──────────────────────────────────────────────────────────────┐
│                        Клиенты                               │
│                                                              │
│   Next.js (Web UI)            Telegram Bot                   │
│   - React 19 + TanStack Query - python-telegram-bot          │
│   - cookie + Bearer token     - AsyncBudgetApiClient         │
│                               - FinanceAdapter (lazy-login)  │
└──────────────┬───────────────────────────┬───────────────────┘
               │                           │
               ▼                           ▼
┌──────────────────────────────────────────────────────────────┐
│                   FastAPI (web/main.py)                       │
│                                                              │
│  AuthMiddleware → защищает /api/* (кроме /api/auth/*)        │
│                                                              │
│  Legacy routes (без auth):     Finance routes (с auth):      │
│  GET/POST  /expenses           GET    /api/finances/summary  │
│  GET/POST  /limits             GET    /api/finances/loans    │
│  PATCH     /limits/{cat}       GET    /api/finances/cards    │
│  DELETE    /limits/{cat}       GET    /api/finances/income   │
│  GET       /report             POST   /api/finances/payments │
│  DELETE    /categories/{name}  GET    /api/finances/accounts │
│  GET       /sync/status        ... и другие                  │
│  GET       /healthz                                          │
│                                                              │
│  Auth routes:                                                │
│  POST /api/auth/login                                        │
│  POST /api/auth/logout                                       │
│  GET  /api/auth/me                                           │
│  GET  /api/auth/status                                       │
└──────────────┬───────────────────────────┬───────────────────┘
               │                           │
               ▼                           ▼
     ┌─────────────────┐       ┌─────────────────────┐
     │  psycopg2 (sync) │       │   asyncpg (async)   │
     │  Legacy таблицы  │       │   Finance таблицы   │
     └────────┬─────────┘       └──────────┬──────────┘
              │                            │
              └──────────────┬─────────────┘
                             ▼
                    ┌─────────────────┐
                    │   PostgreSQL    │
                    │   (Railway)     │
                    └─────────────────┘
```

## Аутентификация

- Сессии хранятся **в памяти** (`active_sessions: Dict[str, User]` в `web/auth/routes.py`)
- При логине генерируется `secrets.token_urlsafe(32)`, кладётся в cookie `session_token` (httpOnly, 30 дней) и возвращается в теле ответа как `token`
- Фронтенд хранит токен в `localStorage` и передаёт его как `Authorization: Bearer <token>` (для совместимости с Safari, который блокирует cross-site cookies)
- `AuthMiddleware` проверяет cookie или Bearer-заголовок
- При рестарте FastAPI все сессии сбрасываются

## Два пути к базе данных

Исторически сложилось разделение на два независимых слоя доступа к БД:

| Слой | Драйвер | Таблицы | Используется в |
|------|---------|---------|----------------|
| Legacy | psycopg2 (sync) | `expenses`, `category_limits`, `monthly_budgets` | `web/postgres_db.py` → legacy routes |
| Finance | asyncpg (async) | `finance_loans`, `finance_credit_cards`, `finance_payments`, `finance_income`, `finance_recurring`, `piggy_banks`, `peers`, `budget_alerts` | `web/finance/repo.py` → `/api/finances/*` |

## Telegram Bot

Бот взаимодействует с API через два адаптера:

- **`services/bot_adapter.py`** → `AsyncBudgetApiClient` (aiohttp) — для legacy операций (расходы, лимиты, отчёты, уведомления)
- **`services/finance_adapter.py`** (requests, sync) — для финансовых операций; при первом вызове делает `POST /api/auth/login` и кэширует сессионный токен; при 401 автоматически перелогинивается

## Поток данных (добавление расхода)

```
Telegram пользователь
      │
      │ текст "Еда 250"
      ▼
   bot.py → text_add()
      │
      │ await add_expense("Еда", 250)
      ▼
   services/bot_adapter.py
      │
      │ POST /expenses {category, amount}
      ▼
   AsyncBudgetApiClient._request()  [aiohttp]
      │
      ▼
   FastAPI POST /expenses
      │
      ▼
   web/postgres_db.add_expense()   [psycopg2]
      │
      ▼
   PostgreSQL → INSERT expenses
      │
      │ (exceeded, remaining)
      ◄──────────────────────────────
      │
      ▼
   bot.py → ответ пользователю + maybe_notify_thresholds()
```

## Plaid Bank Integration

```
Settings UI (Next.js)
      │
      │ POST /api/plaid/link-token
      ▼
   FastAPI → Plaid API → link_token
      │
      │ (Plaid Link UI открывается в браузере)
      │
      │ POST /api/plaid/exchange-token {public_token}
      ▼
   FastAPI → Plaid API → access_token
      │
      │ зашифровать Fernet → сохранить в plaid_items
      ▼
   PostgreSQL

   APScheduler (03:00 daily)
      │
      │ Plaid Transactions Sync API → новые транзакции → expenses
      │ Plaid Balance API → балансы → finance_credit_cards / finance_loans
      ▼
   PostgreSQL
```

## Важные ограничения

- **Сессии в памяти** — горизонтальное масштабирование невозможно; при рестарте сервиса все пользователи разлогиниваются
- **Legacy API без аутентификации** — `/expenses`, `/limits`, `/report` не защищены `AuthMiddleware`; это сделано намеренно для совместимости с ботом, который обращается к ним без токена
- **Два DB-драйвера** — psycopg2 (sync, блокирующий) в legacy routes и asyncpg в финансовом модуле; смешивание не рекомендуется
