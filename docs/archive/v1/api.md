> **ARCHIVED — V1 documentation. Current V2 docs are in [docs/](../../)**

---

# API — Справочник эндпоинтов

Base URL (production): `https://fastapi-production-eadf.up.railway.app`

## Аутентификация

Большинство `/api/*` маршрутов защищены. Передавай токен одним из двух способов:
- Cookie: `session_token=<token>`
- Header: `Authorization: Bearer <token>`

### POST /api/auth/login

Авторизация. Возвращает cookie и токен.

**Тело запроса:**
```json
{ "username": "admin", "password": "..." }
```

**Ответ:**
```json
{
  "success": true,
  "message": "Login successful",
  "user": { "username": "admin", "logged_in_at": "2026-04-15T10:00:00" },
  "token": "<session_token>"
}
```

### GET /api/auth/status

Проверка статуса сессии.

```json
{ "authenticated": true }
```

### POST /api/auth/logout

Завершение сессии.

---

## Расходы (Legacy, без auth)

### GET /expenses?month=YYYY-MM

Список расходов за месяц.

**Query-параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `month` | string | Обязательный. Формат `YYYY-MM` |
| `query` | string | Поиск: диапазоны сумм (`100..300`), операторы (`>100`, `<=50`), даты (`2026-04`), подстрока категории |
| `source` | string | Фильтр по источнику: `manual`, `plaid`, `plaid_sandbox` |

**Ответ:**
```json
[
  {
    "id": 1,
    "category": "Еда",
    "amount": 45.50,
    "date": "2026-04-15",
    "source": "plaid",
    "merchant_name": "Whole Foods Market",
    "plaid_category_raw": "[\"Food and Drink\", \"Groceries\"]",
    "plaid_pfc_category": "GROCERIES",
    "is_pending": false
  }
]
```

> Поля `merchant_name`, `plaid_category_raw`, `plaid_pfc_category`, `is_pending` заполнены только для транзакций из Plaid; для ручных записей — `null`.

### POST /expenses

Создание расхода вручную (source будет `manual`).

```json
{ "category": "Еда", "amount": 250.0, "date": "2026-04-15" }
```

**Ответ:**
```json
{ "exceeded": false, "remaining": 750.0 }
```

### PATCH /expenses/{id}

Обновление расхода. Поля `category`, `amount`, `date` — все опциональны.

### DELETE /expenses/{id}

Удаление расхода.

---

## Лимиты (Legacy, без auth)

### GET /limits

Список всех лимитов по категориям.

```json
[{ "category": "Еда", "default_limit": 1000.0 }]
```

### POST /limits

Создание или обновление лимита.

```json
{ "category": "Еда", "default_limit": 1000.0 }
```

### PATCH /limits/{category_name}

Обновление лимита или переименование категории.

```json
{ "default_limit": 1200.0 }
```

или с переименованием:
```json
{ "category": "Food", "default_limit": 1200.0 }
```

### DELETE /limits/{category_name}

Удаление лимита и всех расходов категории.

---

## Отчёты (Legacy, без auth)

### GET /report?month=YYYY-MM

Отчёт за месяц. Опциональный параметр `compare=YYYY-MM` для сравнения.

> Строки с `source = 'plaid_sandbox'` **исключаются** из расчётов.

**Ответ:**
```json
{
  "report": {
    "Еда": { "spent": 850.0, "budget": 1000.0, "remaining": 150.0 }
  },
  "comparison": { "Еда": -5.2 }
}
```

---

## Категории (Legacy, без auth)

### DELETE /categories/{name}

Удаление категории и всех её расходов.

---

## Финансы (требуют auth)

Префикс: `/api/finances/`

### GET /api/finances/summary?month=YYYY-MM

Сводка за месяц: доходы, долги, минимальные платежи, повторяющиеся расходы, прогноз закрытия займов.

**Ответ (ключевые поля):**
```json
{
  "income_total_cents": 700000,
  "income_by_person": {
    "Denis": 500000,
    "Taya": 150000,
    "Plaid": 50000
  },
  "debt_totals": {
    "loans_balance_cents": 2500000,
    "cards_balance_cents": 150000,
    "combined_balance_cents": 2650000,
    "min_payments_cents": 75000,
    "recurring_expenses_total_cents": 25000
  }
}
```

> `income_by_person` теперь включает ключ `"Plaid"` для доходов, автоматически импортированных из банка.

### GET /api/finances/loans?is_active=true

Список займов.

### POST /api/finances/loans

Создание займа.

```json
{
  "name": "Автокредит",
  "category_name": "Auto Loan",
  "apr_percent": "5.5",
  "current_balance_cents": 2500000,
  "due_day": 15,
  "min_payment_cents": 50000,
  "remaining_months": 36
}
```

### PATCH /api/finances/loans/{id}

Обновление займа.

### GET /api/finances/cards?is_active=true

Список кредитных карт.

**Ответ включает поля от Plaid Liabilities:**
```json
[{
  "id": 1,
  "name": "Chase Freedom",
  "apr_percent": 24.99,
  "current_balance_cents": 150000,
  "min_payment_cents": 2500,
  "due_day": 20,
  "plaid_account_id": "abc123",
  "last_synced_at": "2026-04-15T03:00:00Z"
}]
```

> `plaid_account_id` и `last_synced_at` заполнены если карта была привязана через Plaid Liabilities синк.

### POST /api/finances/cards

Создание карты.

```json
{
  "name": "Chase Freedom",
  "category_name": "Chase",
  "apr_percent": "24.99",
  "current_balance_cents": 150000,
  "credit_limit_cents": 500000,
  "due_day": 20,
  "min_payment_cents": 2500
}
```

### GET /api/finances/payments?account_type=loan&account_id=1

Список платежей.

### POST /api/finances/payments

Создание платежа.

```json
{
  "account_type": "loan",
  "account_id": 1,
  "amount_cents": 50000,
  "occurred_at": "2026-04-15",
  "person": "Denis",
  "note": "Monthly payment"
}
```

### GET /api/finances/income?month=YYYY-MM

Список доходов за месяц. Опциональный параметр `person` (`Denis`, `Taya`, `Plaid`).

**Ответ:**
```json
[
  {
    "id": 1,
    "person": "Denis",
    "amount_cents": 500000,
    "occurred_at": "2026-04-01",
    "note": "Зарплата",
    "created_at": "2026-04-01T10:00:00Z",
    "plaid_transaction_id": null
  },
  {
    "id": 2,
    "person": "Plaid",
    "amount_cents": 50000,
    "occurred_at": "2026-04-03",
    "note": "Direct Deposit",
    "created_at": "2026-04-03T03:00:00Z",
    "plaid_transaction_id": "txn_abc123"
  }
]
```

### POST /api/finances/income

Добавление дохода вручную. Поле `person` принимает `Denis`, `Taya` или `Plaid`.

```json
{
  "person": "Denis",
  "amount_cents": 500000,
  "occurred_at": "2026-04-01",
  "note": "Зарплата"
}
```

> Доходы с `person = 'Plaid'` автоматически импортируются при синке с Plaid и имеют заполненный `plaid_transaction_id`. Редактирование через UI для таких записей заблокировано.

### GET /api/finances/recurring-expenses?active_only=true

Повторяющиеся расходы.

### GET /api/finances/piggy-banks

Копилки.

### POST /api/finances/piggy-banks/{id}/add-amount

Пополнение копилки.

```json
{ "amount_cents": 10000 }
```

### GET /api/finances/accounts

Сводный список всех счетов (займы + карты).

### GET /api/finances/analytics/interest-summary?month=YYYY-MM

Аналитика процентов за месяц.

### GET /api/finances/analytics/account/{type}/{id}

Детальная аналитика по счёту. `type` — `loan` или `card`.

---

## Plaid (требуют auth)

Префикс: `/api/plaid/`

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/plaid/link-token` | Создать link_token для Plaid Link UI |
| POST | `/api/plaid/exchange-token` | Обменять public_token → сохранить access_token |
| GET | `/api/plaid/items` | Список подключённых банков |
| DELETE | `/api/plaid/items/{item_id}` | Отключить банк |
| POST | `/api/plaid/sync` | Запустить синхронизацию вручную |
| GET | `/api/plaid/sync/log` | История последних 50 синхронизаций |
| GET | `/api/plaid/category-map` | Получить маппинг Plaid → budget категорий |
| PATCH | `/api/plaid/category-map` | Обновить маппинг категорий |

---

## Здоровье

### GET /healthz

```json
{ "ok": true }
```

---

## Sync (заглушки)

Эндпоинты `/sync/status`, `/sync/pull`, `/sync/push` существуют для обратной совместимости, но GitHub-синхронизация отключена — используется PostgreSQL напрямую.
