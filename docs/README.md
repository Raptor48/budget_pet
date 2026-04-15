# Budget Pet — Семейный бюджет-трекер

## Назначение

Budget Pet — приложение для ведения семейного бюджета. Позволяет отслеживать расходы по категориям, управлять лимитами, анализировать финансы (займы, кредитные карты, доходы, накопления) и получать уведомления через Telegram.

## Компоненты

| Компонент | Технология | Назначение |
|-----------|-----------|------------|
| **FastAPI backend** | Python 3.11, FastAPI, PostgreSQL | REST API для всех данных |
| **Next.js frontend** | Next.js 15, React 19, TypeScript | Веб-интерфейс |
| **Telegram Bot** | python-telegram-bot 22 | Быстрые операции и уведомления |
| **PostgreSQL** | Railway Postgres | Хранение всех данных |

## Технологический стек

**Backend:**
- Python 3.11
- FastAPI + Uvicorn
- PostgreSQL: `psycopg2-binary` (legacy CRUD) + `asyncpg` (финансовый модуль)
- Pydantic v2

**Frontend:**
- Next.js 15.5, React 19
- TypeScript 5, Tailwind CSS 4
- TanStack Query, Radix UI, Recharts, react-hook-form + zod

**Инфраструктура:**
- Railway (деплой, PostgreSQL)
- Docker (образ `python:3.11-slim`)
- Procfile для воркера бота

## Деплой на Railway

Проект содержит три сервиса на Railway:

1. **FastAPI** — основной веб-сервис (uvicorn `web.main:app`)
2. **Next.js (Web UI)** — фронтенд
3. **telegram bot** — воркер (`python bot.py`)
4. **Postgres DB** — база данных

Подробнее: [development.md](development.md)

## Структура репозитория

```
budget_pet/
├── bot.py                   # Точка входа Telegram-бота
├── web/                     # FastAPI приложение
│   ├── main.py              # Роутер, middleware, CORS
│   ├── postgres_db.py       # Синхронный доступ к БД (расходы/лимиты)
│   ├── schemas.py           # Pydantic-схемы legacy API
│   ├── deps.py              # Фабрика логгера
│   ├── auth/                # Аутентификация (сессии)
│   └── finance/             # Финансовый модуль (займы, карты, etc.)
├── services/                # Сервисный слой
│   ├── api_client.py        # Async HTTP-клиент для бота
│   ├── bot_adapter.py       # Обёртки бота над API
│   ├── finance_adapter.py   # Sync HTTP-клиент для финансовых операций
│   ├── search_filter.py     # Фильтрация расходов по запросу
│   ├── logging_config.py    # Настройка логгера
│   └── env_loader.py        # Утилиты окружения
├── frontend/                # Next.js приложение
│   └── src/
│       ├── app/             # Страницы (App Router)
│       ├── components/      # UI-компоненты
│       ├── lib/             # api.ts, auth.ts, utils.ts
│       └── types/           # TypeScript-типы API
├── tests/                   # Тесты (pytest)
├── docs/                    # Документация
│   └── archive/             # Устаревшие документы
├── Dockerfile
├── Procfile
└── requirements.txt
```
