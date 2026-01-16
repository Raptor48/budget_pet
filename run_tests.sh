#!/bin/bash
# Скрипт для запуска тестов

set -e

echo "🧪 Запуск тестов для Budget Pet"
echo ""

# Проверка переменной окружения
if [ -z "$TEST_DATABASE_URL" ]; then
    export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/budget_pet_test"
    echo "⚠️  TEST_DATABASE_URL не установлена, используется: $TEST_DATABASE_URL"
fi

# Проверка подключения к БД
echo "📊 Проверка подключения к тестовой БД..."
python3 -c "
import psycopg2
import os
try:
    conn = psycopg2.connect(os.getenv('TEST_DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/budget_pet_test'))
    conn.close()
    print('✅ Подключение к БД успешно')
except Exception as e:
    print(f'❌ Ошибка подключения к БД: {e}')
    print('💡 Убедитесь, что PostgreSQL запущен и база данных создана:')
    print('   createdb budget_pet_test')
    exit(1)
" || exit 1

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
