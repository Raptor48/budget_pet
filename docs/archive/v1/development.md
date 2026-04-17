> **ARCHIVED — V1 documentation. Current V2 docs are in [docs/](../../)**

---

# Разработка и запуск

## Требования

- Python 3.11+
- Node.js 20+
- PostgreSQL (локально или через Railway)
- Telegram Bot Token (для бота)

## Локальный запуск

### 1. Клонировать репозиторий

```bash
git clone <repo-url>
cd budget_pet
```

### 2. Настроить окружение

Создай файл `.env` в корне проекта (он в `.gitignore`):

```env
# PostgreSQL
DATABASE_URL=postgresql://postgres:password@localhost:5432/budget_pet

# FastAPI URL (для бота и фронтенда)
API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_API_URL=http://localhost:8000

# Аутентификация
ADMIN_LOGIN=admin
ADMIN_PASSWORD=yourpassword

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token
ALLOWED_USERS=123456789

# Валюта бота
BOT_CURRENCY_SYMBOL=$
```

> Для локального фронтенда создай `frontend/.env.local` (он тоже в `.gitignore`):
> ```
> NEXT_PUBLIC_API_URL=http://localhost:8000
> ```

### 3. Установить зависимости Python

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Инициализировать базу данных

Таблицы создаются автоматически при старте FastAPI (`startup_event` в `web/main.py`). Убедись, что PostgreSQL запущен и `DATABASE_URL` указывает на существующую базу.

### 5. Запустить FastAPI

```bash
uvicorn web.main:app --reload --port 8000
```

API будет доступен по адресу: http://localhost:8000  
Документация Swagger: http://localhost:8000/docs

### 6. Запустить Next.js фронтенд

```bash
cd frontend
npm install
npm run dev
```

Фронтенд: http://localhost:3000

### 7. Запустить Telegram бота

```bash
python bot.py
```

---

## Тесты

```bash
# Все тесты
pytest

# С покрытием
pytest --cov=web --cov-report=html

# Конкретный файл
pytest tests/test_calculations.py -v
```

Тесты требуют PostgreSQL. Укажи тестовую БД через переменную `TEST_DATABASE_URL`:
```bash
export TEST_DATABASE_URL=postgresql://postgres:password@localhost:5432/budget_pet_test
pytest
```

### Типы тестов

| Файл | Что тестирует |
|------|--------------|
| `tests/test_calculations.py` | Расчёты процентов и аналитики (unit) |
| `tests/test_finance_repo.py` | FinanceRepository (integration, требует БД) |
| `tests/test_api_endpoints.py` | FastAPI эндпоинты через TestClient |
| `tests/test_budget_calculations.py` | Расчёты бюджета (integration, требует БД) |

---

## Railway: переменные окружения

В Railway Dashboard → Project → Service → Variables установи:

**Сервис FastAPI:**

| Переменная | Значение |
|------------|----------|
| `DATABASE_URL` | Автоматически из Postgres-сервиса |
| `ADMIN_LOGIN` | Логин администратора |
| `ADMIN_PASSWORD` | Пароль администратора |
| `RAILWAY_ENVIRONMENT` | `production` |

**Сервис telegram bot:**

| Переменная | Значение |
|------------|----------|
| `TELEGRAM_BOT_TOKEN` | Токен от @BotFather |
| `API_BASE_URL` | Internal URL FastAPI сервиса |
| `ADMIN_LOGIN` | Тот же, что у FastAPI |
| `ADMIN_PASSWORD` | Тот же, что у FastAPI |
| `ALLOWED_USERS` | Telegram user ID через запятую |
| `BOT_CURRENCY_SYMBOL` | `$` или другой символ |

**Сервис Next.js:**

| Переменная | Значение |
|------------|----------|
| `NEXT_PUBLIC_API_URL` | Public URL FastAPI сервиса |

---

## Деплой

Railway автоматически деплоит при push в `main` (если настроен auto-deploy).

Ручной деплой через Railway CLI:

```bash
# Деплой FastAPI
railway up --service FastAPI

# Посмотреть логи
railway logs --service FastAPI --lines 50
railway logs --service "telegram bot" --lines 50

# Проверить переменные окружения
railway variables --service FastAPI
```

---

## Структура БД

### Legacy таблицы (psycopg2)

- `expenses` — расходы (`id`, `category`, `amount`, `date`)
- `category_limits` — лимиты (`category`, `default_limit`)
- `monthly_budgets` — месячные бюджеты (`month`, `category`, `budget`)

### Finance таблицы (asyncpg)

- `finance_loans` — займы
- `finance_credit_cards` — кредитные карты
- `finance_payments` — платежи по займам/картам
- `finance_income` — доходы
- `finance_recurring` — повторяющиеся расходы
- `piggy_banks` — копилки
- `peers` — Telegram-пользователи для уведомлений
- `budget_alerts` — отправленные пороговые уведомления
