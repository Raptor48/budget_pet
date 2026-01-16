# Анализ проекта Budget Pet

## 📋 Общая информация

**Budget Pet** - комплексное приложение для управления семейным бюджетом с тремя точками входа:
1. **Desktop GUI** (Python + CustomTkinter)
2. **Telegram Bot** (python-telegram-bot)
3. **Web Frontend** (Next.js 15 + React 19)

**Инфраструктура:**
- **Backend API**: FastAPI на Railway
- **База данных**: PostgreSQL на Railway
- **Frontend**: Next.js на Railway
- **Telegram Bot**: Worker на Railway
- **Синхронизация**: Через REST API (GitHub sync отключен)

---

## 🏗️ Архитектура проекта

### Структура компонентов

```
┌─────────────────┐
│  Desktop GUI    │ (app.py + ui/)
│  CustomTkinter  │
└────────┬────────┘
         │ HTTP REST API
         ▼
┌─────────────────┐
│  FastAPI Backend│ (web/main.py)
│  Railway        │
└────────┬────────┘
         │
         ├──► PostgreSQL (Railway)
         │
         │ HTTP REST API
         ▼
┌─────────────────┐
│  Next.js Frontend│ (frontend/)
│  Railway        │
└─────────────────┘

┌─────────────────┐
│  Telegram Bot   │ (bot.py)
│  Railway Worker │
└────────┬────────┘
         │ HTTP REST API
         └──► FastAPI Backend
```

### Технологический стек

**Backend:**
- Python 3.11+
- FastAPI 0.116.1
- PostgreSQL (psycopg2-binary, asyncpg)
- Uvicorn

**Frontend:**
- Next.js 15.5.9
- React 19.1.0
- TypeScript 5
- Tailwind CSS 4
- Radix UI компоненты
- Recharts для графиков

**Desktop:**
- CustomTkinter 5.2.2
- Matplotlib 3.10.5

**Telegram Bot:**
- python-telegram-bot 22.3

---

## 📊 База данных

### Схема PostgreSQL

#### Основные таблицы расходов:
- `expenses` - записи расходов (id, category, amount, date)
- `category_limits` - лимиты по категориям (category, default_limit)
- `monthly_budgets` - месячные бюджеты с переносом (month, category, budget_limit, rolled_over)
- `settings` - настройки приложения (key-value)

#### Финансовые таблицы:
- `finance_loans` - займы (name, apr, balance, min_payment, due_date, remaining_months)
- `finance_credit_cards` - кредитные карты (name, apr, balance, credit_limit, min_payment, due_date)
- `finance_payments` - платежи (account_type, account_id, amount, occurred_at, person, note)
- `finance_income` - доходы (person, amount, occurred_at, note)

#### Вспомогательные таблицы:
- `peers` - пользователи Telegram бота для уведомлений
- `budget_alerts` - отслеживание отправленных уведомлений о порогах

### Особенности:
- Деньги хранятся в центах (integer) для точности
- Поддержка автопереноса остатков между месяцами
- Индексы на часто используемых полях (date, category, is_active)

---

## 🔄 Потоки данных

### 1. Desktop GUI → API
```
app.py → services/api_client.py → FastAPI → PostgreSQL
```
- Синхронные HTTP запросы через `requests`
- Fallback на локальную SQLite (bd.py) - устаревший код

### 2. Telegram Bot → API
```
bot.py → services/bot_adapter.py → AsyncBudgetApiClient → FastAPI → PostgreSQL
```
- Асинхронные HTTP запросы через `aiohttp`
- Поддержка уведомлений между пользователями
- Проверка порогов бюджета (50%, 90%)

### 3. Next.js Frontend → API
```
Next.js Pages → src/lib/api.ts → FastAPI → PostgreSQL
```
- Fetch API с credentials для cookies
- Аутентификация через сессии (cookies)
- Server Components для прямого доступа к БД (только для finances)

---

## 🔐 Аутентификация

### Текущая реализация:
- **Session-based** аутентификация через cookies
- In-memory хранилище сессий (не масштабируется!)
- Credentials: `ADMIN_LOGIN` / `ADMIN_PASSWORD` из env
- Защита маршрутов через `AuthMiddleware`

### Проблемы:
- ❌ Сессии теряются при перезапуске
- ❌ Нет поддержки нескольких пользователей
- ❌ Нет refresh токенов
- ❌ Нет rate limiting

---

## 📁 Структура кода

### Backend (`web/`)
- `main.py` - FastAPI приложение, основные endpoints
- `postgres_db.py` - операции с БД (expenses, limits, reports)
- `finance/` - модуль финансов (loans, cards, payments, income)
  - `routes.py` - API endpoints
  - `repo.py` - репозиторий с бизнес-логикой
  - `models.py` - Pydantic модели
  - `calculations.py` - расчеты процентов и аналитика
- `auth/` - аутентификация
  - `routes.py` - login/logout endpoints
  - `middleware.py` - проверка сессий
  - `models.py` - модели пользователей

### Services (`services/`)
- `api_client.py` - HTTP клиенты (sync/async)
- `bot_adapter.py` - адаптер для бота (async API calls)
- `finance_adapter.py` - адаптер для финансовых операций
- `bd_adapter.py` - устаревший адаптер для SQLite
- `env_loader.py` - загрузка переменных окружения
- `logging_config.py` - настройка логирования
- `search_filter.py` - фильтрация расходов по запросам

### Frontend (`frontend/src/`)
- `app/` - Next.js App Router страницы
  - `page.tsx` - главная (dashboard)
  - `expenses/` - управление расходами
  - `categories/` - управление категориями
  - `finances/` - финансовый модуль (loans, cards, income)
  - `reports/` - отчеты
  - `settings/` - настройки
  - `login/` - страница входа
- `components/` - React компоненты
  - `dashboard/` - компоненты дашборда
  - `expenses/` - формы и таблицы расходов
  - `charts/` - графики (pie, bar charts)
  - `layout/` - layout компоненты (sidebar, app-layout)
- `lib/` - утилиты
  - `api.ts` - API клиент
  - `auth.ts` - функции аутентификации
  - `date-utils.ts` - работа с датами
- `types/` - TypeScript типы
  - `api.ts` - типы для API

### Desktop GUI (`ui/`)
- `main_window.py` - главное окно
- `table_view.py` - таблица расходов
- `charts.py` - графики (matplotlib)
- `dialogs.py` - диалоги добавления/редактирования
- `summary_panel.py` - панель сводки
- `top_panel.py` - верхняя панель с фильтрами

---

## 🔗 Зависимости

### Backend зависимости (requirements.txt):
- **FastAPI** - веб-фреймворк
- **psycopg2-binary** - PostgreSQL драйвер (sync)
- **asyncpg** - PostgreSQL драйвер (async)
- **python-telegram-bot** - Telegram Bot API
- **pydantic** - валидация данных
- **uvicorn** - ASGI сервер
- **requests** / **aiohttp** - HTTP клиенты
- **python-dotenv** - загрузка .env

### Frontend зависимости (package.json):
- **Next.js 15.5.9** - React фреймворк
- **React 19.1.0** - UI библиотека
- **TypeScript 5** - типизация
- **Tailwind CSS 4** - стилизация
- **Radix UI** - компоненты (dialog, select, tabs, etc.)
- **Recharts** - графики
- **React Query** - управление состоянием API
- **Zod** - валидация схем
- **date-fns** - работа с датами

---

## ⚙️ Конфигурация и переменные окружения

### Backend (Railway):
- `DATABASE_URL` - строка подключения PostgreSQL
- `PORT` - порт для FastAPI (автоматически Railway)
- `ADMIN_KEY` - ключ для админских endpoints
- `ADMIN_LOGIN` / `ADMIN_PASSWORD` - учетные данные
- `API_BASE_URL` - URL API (для бота)
- `RAILWAY_ENVIRONMENT` - окружение (production/development)

### Telegram Bot (Railway):
- `TELEGRAM_BOT_TOKEN` - токен бота
- `ALLOWED_USERS` - список разрешенных user_id
- `API_BASE_URL` - URL FastAPI backend
- `BOT_CURRENCY_SYMBOL` - символ валюты ($)

### Frontend (Railway):
- `NEXT_PUBLIC_API_URL` - URL FastAPI backend
- `DATABASE_URL` - для прямого доступа к БД (Server Components)

---

## 🚀 Деплой

### Railway Services:
1. **FastAPI Backend** - Web Service
   - Dockerfile: `FROM python:3.11-slim`
   - Command: `uvicorn web.main:app --host 0.0.0.0 --port $PORT`
   
2. **Next.js Frontend** - Web Service
   - Build: `npm run build`
   - Start: `npm start`
   
3. **Telegram Bot** - Worker Service
   - Command: `python bot.py`
   - Procfile: `worker: python bot.py`

### Особенности деплоя:
- Автоматический деплой из GitHub
- Переменные окружения настраиваются в Railway dashboard
- PostgreSQL создается автоматически Railway
- CORS настроен для production frontend

---

## ✅ Сильные стороны проекта

1. **Модульная архитектура** - четкое разделение на слои
2. **Типизация** - TypeScript на фронтенде, Pydantic на бэкенде
3. **Множественные точки входа** - Desktop, Web, Telegram
4. **Современный стек** - Next.js 15, React 19, FastAPI
5. **Финансовый модуль** - расчет процентов, аналитика
6. **Автоперенос бюджетов** - остатки переносятся между месяцами
7. **Уведомления** - пороги бюджета, уведомления между пользователями

---

## ⚠️ Проблемы и риски

### Критические:

1. **Аутентификация не масштабируется**
   - In-memory сессии теряются при перезапуске
   - Нет поддержки нескольких пользователей
   - Нет refresh токенов

2. **Дублирование кода**
   - `bd.py` (SQLite) и `web/postgres_db.py` (PostgreSQL) - дублирование логики
   - Desktop GUI может использовать устаревший SQLite

3. **Отсутствие миграций БД**
   - Схема создается через `init_tables()` при старте
   - Нет версионирования схемы
   - Нет rollback миграций

4. **Нет обработки ошибок на уровне БД**
   - Нет connection pooling для sync операций
   - Нет retry логики при сбоях БД

### Средние:

5. **Отсутствие тестов**
   - Нет unit тестов
   - Нет integration тестов
   - Нет E2E тестов

6. **Логирование**
   - Базовое логирование, нет структурированных логов
   - Нет централизованного сбора логов

7. **Безопасность**
   - Пароль админа в коде (хотя и из env)
   - Нет rate limiting
   - Нет валидации входных данных на некоторых endpoints

8. **Производительность**
   - Нет кэширования
   - N+1 запросы возможны в некоторых местах
   - Нет пагинации для больших списков

### Низкие:

9. **Документация**
   - README хороший, но нет API документации
   - Нет архитектурных диаграмм
   - Нет описания бизнес-логики

10. **Мониторинг**
    - Нет метрик
    - Нет health checks для БД
    - Нет алертов

---

## 💡 Рекомендации по улучшению

### Приоритет 1 (Критично):

1. **Исправить аутентификацию**
   ```python
   # Вариант 1: Redis для сессий
   # Вариант 2: JWT токены с refresh
   # Вариант 3: Сессии в PostgreSQL
   ```

2. **Убрать дублирование БД кода**
   - Удалить `bd.py` (SQLite)
   - Использовать только PostgreSQL
   - Обновить Desktop GUI для работы только через API

3. **Добавить миграции БД**
   ```python
   # Использовать Alembic для миграций
   # Версионировать схему
   # Поддержка rollback
   ```

4. **Добавить connection pooling**
   ```python
   # Использовать psycopg2.pool для sync
   # Уже есть asyncpg pool для async
   ```

### Приоритет 2 (Важно):

5. **Добавить тесты**
   - Unit тесты для бизнес-логики
   - Integration тесты для API
   - E2E тесты для критичных сценариев

6. **Улучшить безопасность**
   - Rate limiting (slowapi)
   - Валидация всех входных данных
   - Хеширование паролей (bcrypt)
   - HTTPS только в production

7. **Добавить мониторинг**
   - Prometheus метрики
   - Health checks для БД
   - Structured logging (JSON)
   - Sentry для ошибок

8. **Оптимизировать производительность**
   - Redis для кэширования
   - Пагинация для списков
   - Оптимизация запросов (avoid N+1)

### Приоритет 3 (Желательно):

9. **Улучшить документацию**
   - OpenAPI/Swagger документация
   - Архитектурные диаграммы
   - Описание бизнес-логики

10. **Рефакторинг**
    - Вынести константы в config
    - Унифицировать обработку ошибок
    - Добавить типы везде (mypy)

11. **CI/CD**
    - GitHub Actions для тестов
    - Автоматические деплои
    - Pre-commit hooks

12. **Расширение функционала**
    - Экспорт данных (CSV, PDF)
    - Импорт из банковских выписок
    - Мобильное приложение
    - Мультивалютность

---

## 📈 Метрики проекта

### Размер кодовой базы:
- **Backend**: ~15-20 файлов Python
- **Frontend**: ~30-40 компонентов React
- **Desktop GUI**: ~10 файлов Python
- **Telegram Bot**: 1 основной файл + адаптеры

### Сложность:
- **Средняя** - хорошо структурирован, но есть технический долг
- **Масштабируемость**: Низкая (in-memory сессии, нет кэширования)
- **Поддерживаемость**: Средняя (есть дублирование кода)

### Технический долг:
- ⚠️ Дублирование БД логики (SQLite + PostgreSQL)
- ⚠️ In-memory аутентификация
- ⚠️ Отсутствие тестов
- ⚠️ Нет миграций БД

---

## 🎯 Итоговая оценка

### Оценка: **7/10**

**Сильные стороны:**
- ✅ Современный стек технологий
- ✅ Хорошая архитектура (разделение на слои)
- ✅ Множественные точки входа
- ✅ Типизация и валидация данных

**Слабые стороны:**
- ❌ Технический долг (дублирование, нет тестов)
- ❌ Проблемы с масштабированием (аутентификация)
- ❌ Отсутствие мониторинга и метрик
- ❌ Нет миграций БД

**Рекомендация:** Проект готов к использованию, но требует рефакторинга критичных компонентов (аутентификация, БД слой) перед масштабированием.

---

## 📝 План действий

### Краткосрочные (1-2 недели):
1. ✅ Мигрировать Desktop GUI на API (убрать SQLite)
2. ✅ Добавить Redis для сессий
3. ✅ Настроить Alembic для миграций
4. ✅ Добавить базовые тесты

### Среднесрочные (1 месяц):
5. ✅ Улучшить безопасность (rate limiting, валидация)
6. ✅ Добавить мониторинг (метрики, логи)
7. ✅ Оптимизировать производительность (кэш, пагинация)

### Долгосрочные (2-3 месяца):
8. ✅ Расширить функционал (экспорт, импорт)
9. ✅ Улучшить документацию
10. ✅ Настроить CI/CD

---

*Анализ выполнен: 2025-01-27*
