# Plaid — Интеграция с банком

## Назначение

Интеграция с [Plaid](https://plaid.com) позволяет автоматически:
- Импортировать транзакции из Chase (и других банков) в таблицу `expenses`
- Синхронизировать балансы счетов с финансовым модулем (займы, карты)

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
3. В открывшемся Plaid Link выбери Chase → авторизуйся
4. Соединение сохранится — транзакции начнут импортироваться

## Синхронизация

**Автоматически:** каждый день в 03:00 (APScheduler в FastAPI)

**Вручную:** кнопка **Sync** на странице настроек или:
```bash
curl -X POST https://your-api.railway.app/api/plaid/sync \
  -H "Authorization: Bearer <token>"
```

## Что синхронизируется

### Транзакции → expenses

- Импортируются только дебетовые транзакции (расходы, `amount > 0` в Plaid)
- Дубликаты исключаются через `plaid_transaction_id` (уникальный constraint)
- Категория определяется по маппингу (см. ниже)

### Балансы → finance_loans / finance_credit_cards

- Balances API Plaid возвращает текущий баланс каждого счёта
- Совпадение ищется по `LOWER(name)` между Plaid account name и названием займа/карты в БД
- Поле `current_balance_cents` обновляется при каждом sync

## Маппинг категорий

Plaid возвращает свои категории (например `"Food and Drink"`, `"Shops"`). Маппинг настраивается в Settings:

| Plaid Category | Budget Category |
|---------------|-----------------|
| Food and Drink | Еда |
| Travel | Транспорт |
| Shops | Покупки |

Транзакции без маппинга → категория **Uncategorized**.

Таблица в БД: `plaid_category_map (plaid_category, budget_category)`

## Структура модуля

```
web/plaid/
├── __init__.py        # Экспорт plaid_router, init_plaid_repo, start_scheduler
├── client.py          # Обёртка над plaid-python SDK
├── models.py          # Pydantic-модели
├── repo.py            # asyncpg: хранение items, лог, импорт транзакций
├── routes.py          # FastAPI роуты /api/plaid/*
└── scheduler.py       # APScheduler: sync_all_items(), start_scheduler()
```

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
- Институт: **Plaid Bank** (в Plaid Link)
- Логин: `user_good`
- Пароль: `pass_good`

Тестовые транзакции будут созданы автоматически.
