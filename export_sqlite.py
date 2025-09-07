

# Создайте файл export_sqlite.py
cat > export_sqlite.py << 'EOF'
import sqlite3
import json
import os
from pathlib import Path


def export_sqlite_data():
    """Экспортирует данные из SQLite в JSON"""

    # Путь к вашей локальной базе
    db_path = Path.home() / "budget.db"  # или укажите полный путь

    if not db_path.exists():
        print(f"❌ База данных не найдена: {db_path}")
        print("Проверьте путь к файлу budget.db")
        return

    print(f"📂 Подключение к: {db_path}")

    try:
        # Подключение к SQLite
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Экспорт расходов
        print("📊 Экспорт расходов...")
        cursor.execute('SELECT id, category, amount, date FROM expenses ORDER BY date DESC')
        expenses = cursor.fetchall()

        # Экспорт лимитов (бюджетов)
        print("💰 Экспорт лимитов...")
        cursor.execute('SELECT category, amount FROM limits')
        limits = cursor.fetchall()

        # Экспорт категорий (если есть таблица categories)
        categories = []
        try:
            cursor.execute('SELECT name FROM categories ORDER BY name')
            categories = [row[0] for row in cursor.fetchall()]
            print("📂 Экспорт категорий...")
        except sqlite3.OperationalError:
            print("⚠️  Таблица categories не найдена, пропускаем")

        # Подготовка данных для экспорта
        data = {
            'expenses': [
                {
                    'id': exp[0],
                    'category': exp[1],
                    'amount': exp[2],
                    'date': exp[3]
                } for exp in expenses
            ],
            'limits': [
                {
                    'category': lim[0],
                    'amount': lim[1]
                } for lim in limits
            ],
            'categories': categories
        }

        # Сохранение в JSON
        output_file = 'migration_data.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print("✅ Данные экспортированы!"
        print(f"📄 Файл: {output_file}")
        print(f"📊 Расходов: {len(expenses)}")
        print(f"💰 Лимитов: {len(limits)}")
        print(f"📂 Категорий: {len(categories)}")

        # Показать пример данных
        if expenses:
            print("\n📋 Пример последнего расхода:")
        last_expense = data['expenses'][0]
        print(f"  Категория: {last_expense['category']}")
        print(f"  Сумма: ${last_expense['amount']}")
        print(f"  Дата: {last_expense['date']}")

        conn.close()

    except Exception as e:
        print(f"❌ Ошибка экспорта: {e}")
        return False

    return True


if __name__ == "__main__":
    export_sqlite_data()
EOF