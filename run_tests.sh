#!/bin/bash
# Test runner for Budget Pet.

set -e

echo "Running Budget Pet tests"
echo ""

if [ -z "$TEST_DATABASE_URL" ]; then
    export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/budget_pet_test"
    echo "TEST_DATABASE_URL not set, using default: $TEST_DATABASE_URL"
fi

# Sanity-check DB reachability via asyncpg (same driver as production).
# We intentionally do not depend on psycopg2 just for this probe.
echo "Pinging test database..."
python3 - <<'PY' || exit 1
import asyncio
import os
import sys

import asyncpg


async def _ping() -> None:
    url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/budget_pet_test",
    )
    try:
        conn = await asyncpg.connect(url)
    except Exception as exc:  # noqa: BLE001 — top-level script, want the message
        print(f"ERROR: cannot connect to test DB: {exc}", file=sys.stderr)
        print("Hint: start PostgreSQL and run: createdb budget_pet_test", file=sys.stderr)
        sys.exit(1)
    await conn.close()
    print("DB connection OK")


asyncio.run(_ping())
PY

echo ""

# Запуск тестов
echo "🚀 Запуск pytest..."
echo ""

if [ "$1" == "--coverage" ]; then
    echo "📊 Запуск с покрытием кода..."
    pytest --cov=web --cov=services --cov-report=term --cov-report=html -v
    echo ""
    echo "📈 Отчет покрытия сохранен в htmlcov/index.html"
elif [ "$1" == "--verbose" ]; then
    pytest -v -s
elif [ "$1" == "--calculations" ]; then
    echo "🧮 Тесты финансовых расчетов..."
    pytest tests/test_calculations.py -v
elif [ "$1" == "--budget" ]; then
    echo "💰 Тесты бюджетных расчетов..."
    pytest tests/test_budget_calculations.py -v
elif [ "$1" == "--finance" ]; then
    echo "💳 Тесты финансового модуля..."
    pytest tests/test_finance_repo.py -v
elif [ "$1" == "--api" ]; then
    echo "🌐 Тесты API endpoints..."
    pytest tests/test_api_endpoints.py -v
else
    pytest -v
fi

echo ""
echo "✅ Тесты завершены!"
