> **ARCHIVED — V1 documentation. Current V2 docs are in [docs/](../../)**

---

# Plaid — Интеграция с банком

## Назначение

Интеграция с [Plaid](https://plaid.com) позволяет автоматически:
- Импортировать транзакции (расходы и доходы) из банковских счетов
- Синхронизировать балансы, APR, минимальные платежи по картам и займам через Liabilities API
- Разграничивать авто-импортированные и ручные данные через поле `source`

## Регистрация и настройка

1. Зарегистрируйся на [dashboard.plaid.com](https://dashboard.plaid.com)
2. Создай приложение → получи `PLAID_CLIENT_ID` и `PLAID_SECRET`
3. Начни в режиме **Sandbox** (тестовые данные, бесплатно)
4. Для реальных данных переключись на **Development** (до 100 аккаунтов бесплатно)

## Переменные окружения

Добавить в Railway Variables (сервис **FastAPI**) и в `.env` локально:

| Переменная | Описание |
|------------|----------|
| `PLAID_CLIENT_ID` | Идентификатор приложения из Plaid Dashboard |
| `PLAID_SECRET` | Секрет из Plaid Dashboard |
| `PLAID_ENV` | `sandbox` / `development` / `production` |
| `PLAID_ENCRYPTION_KEY` | Fernet-ключ для шифрования access_token в БД |

Генерация ключа шифрования:
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Как подключить банк (пользователь)

1. Зайди в **Settings → Bank Connections**
2. Нажми **Connect Bank**
3. В открывшемся Plaid Link выбери банк → авторизуйся
4. Соединение сохранится — транзакции начнут импортироваться при следующем синке

## Синхронизация

**Автоматически:** каждый день в 03:00 (APScheduler в FastAPI)

**Вручную:** кнопка **Sync** на странице настроек или:
```bash
curl -X POST https://your-api.railway.app/api/plaid/sync \
  -H "Authorization: Bearer <token>"
```

## Продукты Plaid

В `link_token_create` включены два продукта:

| Продукт | Данные |
|---------|--------|
| `transactions` | История транзакций, merchant name, категории, pending-статус |
| `liabilities` | APR, минимальный платёж, дата платежа, кредитный лимит |

## Что синхронизируется

### Расходы → таблица `expenses`

Транзакции с `amount > 0` (деньги уходят со счёта) импортируются в таблицу `expenses` со следующими полями:

| Поле в expenses | Источник из Plaid |
|----------------|-------------------|
| `category` | Маппинг `plaid_category_map`; при отсутствии — `Uncategorized` |
| `amount` | `transaction.amount` |
| `date` | `transaction.date` |
| `merchant_name` | `transaction.merchant_name` или `transaction.name` |
| `plaid_category_raw` | JSON-массив `transaction.category` (напр. `["Food and Drink","Restaurants"]`) |
| `plaid_pfc_category` | `transaction.personal_finance_category.detailed` |
| `is_pending` | `transaction.pending` |
| `plaid_account_id` | `transaction.account_id` |
| `plaid_transaction_id` | `transaction.transaction_id` (уникальный, для дедупликации) |
| `source` | `plaid_sandbox` если `PLAID_ENV=sandbox`, иначе `plaid` |

При повторном синке (ON CONFLICT DO UPDATE) обновляются: `is_pending`, `merchant_name`, `plaid_category_raw`, `plaid_pfc_category`.

### Доходы → таблица `finance_income`

Транзакции с `amount < 0` (деньги приходят на счёт) импортируются в `finance_income` с:
- `person = 'Plaid'`
- `amount_cents = abs(amount) * 100`
- `note` = merchant_name транзакции
- `plaid_transaction_id` — для дедупликации

Фильтрация: транзакции с `personal_finance_category.primary` из списка non-income (GENERAL_MERCHANDISE, FOOD_AND_DRINK и др.) пропускаются как возвраты/рефанды.

### Балансы → finance_credit_cards / finance_loans

Plaid Balance API возвращает текущий баланс каждого счёта. Совпадение ищется по `LOWER(name)` → обновляется `current_balance_cents`.

### Liabilities → APR, минимальные платежи

При синке вызывается `liabilities/get`. Для каждой кредитной карты обновляются:
- `apr_percent` (из `aprs[].apr_percentage`, тип purchase)
- `min_payment_cents`
- `current_balance_cents` (из `last_statement_balance`)
- `due_day` (день из `next_payment_due_date`)

Сопоставление карт с Plaid идёт по `plaid_account_id`. Для займов аналогично обновляются `apr_percent` и `min_payment_cents`.

## Разграничение реальных и тестовых данных

Поле `source` в таблице `expenses`:

| Значение | Описание |
|----------|----------|
| `manual` | Добавлено вручную через UI или бот |
| `plaid` | Импортировано из Plaid (production / development) |
| `plaid_sandbox` | Импортировано из Plaid Sandbox (тестовые данные) |

Строки с `source = 'plaid_sandbox'` **исключаются** из отчётов и статистики (`/report`, `get_month_report`), но видны в Expenses при выборе фильтра **Test**.

## Маппинг категорий

Plaid возвращает свои категории (например `"Food and Drink"`, `"Shops"`). Маппинг настраивается в Settings → Bank Connections:

| Plaid Category | Budget Category |
|---------------|-----------------|
| Food and Drink | Еда |
| Travel | Транспорт |
| Shops | Покупки |

Транзакции без маппинга → категория **Uncategorized** (в UI показывается предупреждение ⚠).

Таблица в БД: `plaid_category_map (plaid_category, budget_category)`

## UI — страница Expenses

В таблице расходов теперь видны:
- **Merchant** — название мерчанта из Plaid
- **Category** — budget-категория (редактируемая) + Plaid raw category как мелкий breadcrumb (`Food and Drink › Restaurants`)
- **Source** — цветной badge: Manual (серый), Plaid (синий), Test (оранжевый)
- Строки в статусе `pending` — полупрозрачны с меткой *(pending)*
- ⚠ иконка на строках с категорией `Uncategorized` — ссылка на Settings для настройки маппинга
- **Total** — итоговая сумма за месяц в заголовке таблицы

Фильтры: **All / Manual / Plaid / Test**

## Структура модуля

```
web/plaid/
├── __init__.py        # Экспорт plaid_router, init_plaid_repo, start_scheduler
├── client.py          # Обёртка над plaid-python SDK (transactions, balance, liabilities)
├── models.py          # Pydantic-модели
├── repo.py            # asyncpg: init_tables, import_transactions, import_income,
│                      #   sync_balances, sync_liabilities, log_sync
├── routes.py          # FastAPI роуты /api/plaid/*
└── scheduler.py       # APScheduler: sync_all_items(), start_scheduler()
```

## Таблицы БД (Plaid)

| Таблица | Назначение |
|---------|------------|
| `plaid_items` | Подключённые банки (item_id, access_token зашифрован, cursor) |
| `plaid_sync_log` | История синков (transactions_added, income_added, balances_updated, status) |
| `plaid_category_map` | Маппинг Plaid categories → budget categories |

## API эндпоинты

Все эндпоинты защищены аутентификацией (`AuthMiddleware`).

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/plaid/link-token` | Создать link_token для Plaid Link UI |
| POST | `/api/plaid/exchange-token` | Обменять public_token → сохранить access_token |
| GET | `/api/plaid/items` | Список подключённых банков |
| DELETE | `/api/plaid/items/{item_id}` | Отключить банк |
| POST | `/api/plaid/sync` | Запустить синхронизацию вручную |
| GET | `/api/plaid/sync/log` | История последних 50 синхронизаций |
| GET | `/api/plaid/category-map` | Получить маппинг категорий |
| PATCH | `/api/plaid/category-map` | Обновить маппинг категорий |

## Безопасность

- `access_token` хранится в БД **зашифрованным** (Fernet symmetric encryption)
- Ключ шифрования (`PLAID_ENCRYPTION_KEY`) — только в env-переменных, никогда в коде
- Plaid credentials никогда не передаются на фронтенд — все вызовы Plaid API только через FastAPI

## Sandbox-тестирование

В режиме `PLAID_ENV=sandbox` используй тестовые данные Plaid:
- Телефон: `+14155550123` (OTP: `1234`)
- Институт: **Plaid Bank** → логин: `user_good`, пароль: `pass_good`

Тестовые транзакции создаются автоматически. После синка они будут видны в Expenses с фильтром **Test** и **не влияют** на статистику.

Для перехода на реальные банки: смени `PLAID_ENV=development` в Railway Variables.
