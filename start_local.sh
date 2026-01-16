#!/bin/bash
# Скрипт для запуска проекта локально

set -e

echo "🚀 Запуск Budget Pet локально"
echo ""

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден"
    exit 1
fi

echo "✅ Python: $(python3 --version)"

# Проверка зависимостей
echo ""
echo "📦 Проверка зависимостей..."
if ! python3 -c "import fastapi, uvicorn" 2>/dev/null; then
    echo "⚠️  Зависимости не установлены. Устанавливаю..."
    pip3 install -r requirements.txt
fi
echo "✅ Зависимости установлены"

# Проверка .env файла
if [ ! -f .env ]; then
    echo ""
    echo "⚠️  .env файл не найден"
    echo "📝 Создайте .env файл с переменными:"
    echo "   DATABASE_URL=postgresql://user:pass@localhost:5432/dbname"
    echo "   PORT=8000"
    echo ""
    read -p "Продолжить без .env? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✅ .env файл найден"
fi

# Загрузка переменных окружения
export PYTHONPATH="/Users/denisstolpovskii/PycharmProjects/budget_pet:$PYTHONPATH"

# Проверка DATABASE_URL
if [ -z "$DATABASE_URL" ]; then
    if [ -f .env ]; then
        export $(cat .env | grep -v '^#' | xargs)
    fi
fi

if [ -z "$DATABASE_URL" ]; then
    echo ""
    echo "⚠️  DATABASE_URL не установлен"
    echo "   Установите переменную окружения или добавьте в .env"
    echo "   Пример: DATABASE_URL=postgresql://user:pass@localhost:5432/budget_pet"
    echo ""
    read -p "Продолжить без DATABASE_URL? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Установка порта
export PORT=${PORT:-8000}

echo ""
echo "🌐 Запуск FastAPI сервера на порту $PORT..."
echo "   API будет доступен по адресу: http://localhost:$PORT"
echo "   Документация: http://localhost:$PORT/docs"
echo ""
echo "   Для остановки нажмите Ctrl+C"
echo ""

# Запуск сервера
cd /Users/denisstolpovskii/PycharmProjects/budget_pet
uvicorn web.main:app --host 0.0.0.0 --port $PORT --reload
