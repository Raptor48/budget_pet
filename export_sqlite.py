import sqlite3
import json
import os
from pathlib import Path


def export_sqlite_data():
    """Экспортирует данные из SQLite в JSON"""

    # # УКАЖИТЕ ПУТЬ К ВАШЕЙ БАЗЕ ДАННЫХ ЗДЕСЬ:
    # db_path = Path.home() / "budget.db"  # Попробуйте этот путь


    db_path = Path("/Users/denisstolpovskii/PycharmProjects/budget_pet/budget.db")

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

        # Получаем все бюджеты (из category_limits)
        print("💰 Получаем бюджеты...")
        cursor.execute('SELECT category, default_limit FROM category_limits')
        category_limits = cursor.fetchall()

        # Получаем месячные бюджеты
        print("📅 Получаем месячные бюджеты...")
        cursor.execute('SELECT month, category, budget_limit FROM monthly_budgets ORDER BY month DESC')
        monthly_budgets = cursor.fetchall()

        print(f"📊 Найдено расходов: {len(expenses)}")
        print(f"💰 Найдено лимитов категорий: {len(category_limits)}")
        print(f"📅 Найдено месячных бюджетов: {len(monthly_budgets)}")

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
            'category_limits': [
                {
                    'category': lim[0],
                    'default_limit': lim[1]
                } for lim in category_limits
            ],
            'monthly_budgets': [
                {
                    'month': budg[0],
                    'category': budg[1],
                    'budget_limit': budg[2]
                } for budg in monthly_budgets
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

        if category_limits:
            print("\n💰 Пример лимита категории:")
            first_limit = data['category_limits'][0]
            print(f"  Категория: {first_limit['category']}")
            print(f"  Лимит: ${first_limit['default_limit']}")

        if monthly_budgets:
            print("\n📅 Пример месячного бюджета:")
            first_budget = data['monthly_budgets'][0]
            print(f"  Месяц: {first_budget['month']}")
            print(f"  Категория: {first_budget['category']}")
            print(f"  Бюджет: ${first_budget['budget_limit']}")

        conn.close()

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

    return True


if __name__ == "__main__":
    export_sqlite_data()