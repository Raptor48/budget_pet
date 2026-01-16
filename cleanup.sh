#!/bin/bash
# Скрипт для безопасной очистки проекта от мертвых файлов

set -e

echo "🧹 Очистка проекта Budget Pet"
echo ""

# Создаем backup ветку
echo "📦 Создание backup ветки..."
git branch cleanup-backup-$(date +%Y%m%d) 2>/dev/null || echo "Backup ветка уже существует или не git репозиторий"
echo ""

# Функция для безопасного удаления
safe_remove() {
    if [ -f "$1" ] || [ -d "$1" ]; then
        echo "  ❌ Удаление: $1"
        rm -rf "$1"
    else
        echo "  ⚠️  Файл не найден: $1"
    fi
}

echo "🗑️  Удаление backup файлов..."
safe_remove "app.py.backup"
safe_remove "bot.py.backup"
safe_remove "bot_github.py.backup"
echo ""

echo "🗑️  Удаление миграционных скриптов..."
safe_remove "create_postgres_tables.py"
safe_remove "export_sqlite.py"
safe_remove "import_postgres.py"
safe_remove "fix_postgres_schema.py"
safe_remove "execute_sql_auto.py"
safe_remove "compare_telegram_vs_railway.py"
echo ""

echo "🗑️  Удаление аналитических скриптов..."
safe_remove "analyze_telegram_data.py"
safe_remove "parse_telegram_expenses.py"
safe_remove "telegram_import.py"
safe_remove "advanced_dead_code_analyzer.py"
safe_remove "find_dead_code.py"
echo ""

echo "🗑️  Удаление временных данных..."
safe_remove "telegram_expenses.json"
safe_remove "telegram_expenses.sql"
safe_remove "advanced_dead_code_report.json"
safe_remove "dead_code_report.json"
safe_remove "frontend/result.json"
echo ""

echo "🗑️  Удаление неиспользуемых файлов..."
safe_remove "bot_api.py"
safe_remove "github_sync.py"  # Корневой файл, есть services/github_sync.py
echo ""

echo "⚠️  Файлы, требующие проверки (НЕ удаляются автоматически):"
echo "  - bd.py (старый SQLite код)"
echo "  - base.py (старый GUI)"
echo "  - ui/ (старые GUI компоненты)"
echo "  - app.py (Desktop GUI entry point)"
echo "  - services/bd_adapter.py (адаптер для bd.py)"
echo "  - services/github_sync.py (проверить использование)"
echo "  - budget.db (SQLite БД, если не используется)"
echo ""

echo "✅ Безопасная очистка завершена!"
echo ""
echo "📝 Следующие шаги:"
echo "  1. Проверьте, что все работает: pytest"
echo "  2. Если Desktop GUI не используется, можно удалить:"
echo "     rm bd.py base.py app.py services/bd_adapter.py"
echo "     rm -rf ui/"
echo "  3. Проверьте использование services/github_sync.py"
echo "  4. Закоммитьте изменения: git add -A && git commit -m 'Cleanup: remove dead code'"
