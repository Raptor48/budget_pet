import sqlite3
import json
import os
from pathlib import Path


def export_sqlite_data():
    """Экспортирует данные из SQLite в JSON"""

    # УКАЖИТЕ ПУТЬ К ВАШЕЙ БАЗЕ ДАННЫХ ЗДЕСЬ:
    db_path = Path.home() / "budget.db"  # Попробуйте этот путь

    # Если база не там, замените на правильный путь:
    # db_path = Path("/Users/ВАШЕ_ИМЯ/папка/budget.db")

    if not db_path.exists():
        print(f"❌ База данных не найдена: {db_path}")
        print("Найдите файл budget.db и укажите правильный путь выше")
        return

    print(f"📂 Подключение к: {db_path}")

    try:
        # Подключение к SQLite
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Получаем все расходы
        print("📊 Получаем расходы...")
        cursor.execute('SELECT id, category, amount, date FROM expenses ORDER BY date DESC')
        expenses = cursor.fetchall()

        # Получаем все бюджеты
        print("💰 Получаем бюджеты...")
        cursor.execute('SELECT category, amount FROM limits')
        limits = cursor.fetchall()

        print(f"📊 Найдено расходов: {len(expenses)}")
        print(f"💰 Найдено бюджетов: {len(limits)}")

        # Создаем данные для экспорта
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
            ]
        }

        # Сохраняем в файл
        output_file = 'migration_data.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print("✅ Данные сохранены!")
        print(f"📄 Файл: {output_file}")

        # Показываем пример данных
        if expenses:
            print("\n📋 Пример последнего расхода:")
            last_expense = data['expenses'][0]
            print(f"  Категория: {last_expense['category']}")
            print(f"  Сумма: ${last_expense['amount']}")
            print(f"  Дата: {last_expense['date']}")

        conn.close()

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

    return True


if __name__ == "__main__":
    export_sqlite_data()