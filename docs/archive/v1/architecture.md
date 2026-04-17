> **ARCHIVED — V1 documentation. Current V2 docs are in [docs/](../../)**

---

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
│  GET       /healthz            ... и другие                  │
│                                                              │
│  Plaid routes (с auth):        Auth routes:                  │
│  POST /api/plaid/link-token    POST /api/auth/login          │
│  POST /api/plaid/exchange-token POST /api/auth/logout        │
│  POST /api/plaid/sync          GET  /api/auth/me             │
│  GET  /api/plaid/items         GET  /api/auth/status         │
│  GET  /api/plaid/sync/log                                    │
│  GET/PATCH /api/plaid/category-map                           │
└──────────────┬───────────────────────────┬───────────────────┘
               │                           │
               ▼                           ▼
     ┌─────────────────┐       ┌─────────────────────┐
     │  psycopg2 (sync) │       │   asyncpg (async)   │
     │  Legacy таблицы  │       │   Finance + Plaid   │
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
| Finance + Plaid | asyncpg (async) | `finance_loans`, `finance_credit_cards`, `finance_payments`, `finance_income`, `finance_recurring_expenses`, `piggy_banks`, `peers`, `budget_alerts`, `plaid_items`, `plaid_sync_log`, `plaid_category_map` | `web/finance/repo.py`, `web/plaid/repo.py` → `/api/finances/*`, `/api/plaid/*` |

## Схема таблицы `expenses`

```sql
expenses (
  id                    SERIAL PRIMARY KEY,
  category              TEXT NOT NULL,
  amount                NUMERIC NOT NULL,
  date                  TEXT NOT NULL,
  -- Plaid-related (заполняются только для автоимпорта):
  plaid_transaction_id  TEXT UNIQUE,
  source                TEXT NOT NULL DEFAULT 'manual',  -- manual|plaid|plaid_sandbox
  merchant_name         TEXT,
  plaid_category_raw    TEXT,     -- JSON: ["Food and Drink","Restaurants"]
  plaid_pfc_category    TEXT,     -- personal_finance_category.detailed
  is_pending            BOOLEAN DEFAULT FALSE,
  plaid_account_id      TEXT
)
```

## Схема таблицы `finance_income`

```sql
finance_income (
  id                    SERIAL PRIMARY KEY,
  person                TEXT CHECK (person IN ('Denis','Taya','Plaid')),
  amount_cents          BIGINT NOT NULL,
  occurred_at           DATE NOT NULL,
  note                  TEXT,
  created_at            TIMESTAMPTZ DEFAULT NOW(),
  plaid_transaction_id  TEXT UNIQUE  -- заполнено для Plaid-доходов
)
```

## Telegram Bot

Бот взаимодействует с API через два адаптера:

- **`services/bot_adapter.py`** → `AsyncBudgetApiClient` (aiohttp) — для legacy операций (расходы, лимиты, отчёты, уведомления)
- **`services/finance_adapter.py`** (requests, sync) — для финансовых операций; при первом вызове делает `POST /api/auth/login` и кэширует сессионный токен; при 401 автоматически перелогинивается

## Поток данных: добавление расхода вручную

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
      │ POST /expenses {category, amount, source="manual"}
      ▼
   FastAPI POST /expenses
      │
      ▼
   web/postgres_db.add_expense()   [psycopg2]
      │
      ▼
   PostgreSQL → INSERT expenses (source='manual')
      │
      │ (exceeded, remaining)
      ◄──────────────────────────────
      │
      ▼
   bot.py → ответ пользователю + maybe_notify_thresholds()
```

## Поток данных: Plaid Bank Sync

```
Settings UI (Next.js)
      │
      │ POST /api/plaid/link-token
      ▼
   FastAPI → Plaid API (transactions + liabilities products)
      │        → link_token
      │
      │ (Plaid Link UI открывается в браузере)
      │
      │ POST /api/plaid/exchange-token {public_token}
      ▼
   FastAPI → Plaid API → access_token
      │
      │ Fernet encrypt → сохранить в plaid_items
      ▼
   PostgreSQL

   APScheduler (03:00 daily) / POST /api/plaid/sync
      │
      ├─ transactions/sync
      │     ├─ amount > 0 → INSERT expenses
      │     │     (merchant_name, plaid_category_raw, plaid_pfc_category,
      │     │      is_pending, plaid_account_id, source)
      │     └─ amount < 0 → INSERT finance_income (person='Plaid')
      │
      ├─ accounts/balance/get
      │     └─ UPDATE finance_credit_cards / finance_loans (current_balance_cents)
      │
      └─ liabilities/get
            ├─ credit cards → UPDATE apr_percent, min_payment_cents, due_day
            └─ student loans → UPDATE apr_percent, min_payment_cents
      │
      ▼
   PostgreSQL
      │
      └─ INSERT plaid_sync_log (transactions_added, income_added, balances_updated)
```

## Математика дашборда

| Метрика | Формула |
|---------|---------|
| Budget Remaining | `SUM(budget - spent)` по всем категориям − `recurring_expenses_total` |
| Net Income | `income_total` − `min_payments` − `recurring_expenses_total` |
| Payments & Subscriptions | `min_payments + recurring_expenses_total` |

> Строки `source = 'plaid_sandbox'` исключаются из всех расчётов `SUM(spent)`.

## Важные ограничения

- **Сессии в памяти** — горизонтальное масштабирование невозможно; при рестарте сервиса все пользователи разлогиниваются
- **Legacy API без аутентификации** — `/expenses`, `/limits`, `/report` не защищены `AuthMiddleware`; это сделано намеренно для совместимости с ботом
- **Два DB-драйвера** — psycopg2 (sync, блокирующий) в legacy routes и asyncpg в финансовом модуле; смешивание не рекомендуется
- **Liabilities matching** — сопоставление карт/займов с Plaid идёт по `plaid_account_id`; карты добавленные вручную до подключения Plaid не имеют `plaid_account_id` и не обновляются через Liabilities API автоматически
