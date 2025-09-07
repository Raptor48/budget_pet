import json
import os
from urllib.parse import urlparse
import psycopg2
from psycopg2.extras import execute_values

def import_to_postgres():
    """Импортирует данные в PostgreSQL"""

    # ДЛЯ ЛОКАЛЬНОГО ИМПОРТА ИСПОЛЬЗУЙТЕ ПУБЛИЧНЫЙ URL:
    database_url = "postgresql://postgres:qLyWBUAaVUsEIaQtfQmtMlsAWFyNJBIw@roundhouse.proxy.rlwy.net:44861/railway"

    # Получите публичный URL из Railway dashboard → PostgreSQL → Variables → DATABASE_PUBLIC_URL
    # Приватный URL используйте только в Railway сервисах (FastAPI, Next.js)

    print("🔗 Подключение к PostgreSQL...")

    try:
        # Парсим строку подключения
        parsed = urlparse(database_url)

        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path[1:]  # убираем слэш
        )

        cursor = conn.cursor()

        # Загружаем данные из JSON
        print("📂 Загружаем данные из migration_data.json...")
        with open('migration_data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Импортируем лимиты категорий
        if data.get('category_limits'):
            print("💰 Импортируем лимиты категорий...")
            limits_data = [(lim['category'], lim['default_limit']) for lim in data['category_limits']]
            execute_values(
                cursor,
                "INSERT INTO category_limits (category, default_limit) VALUES %s ON CONFLICT (category) DO UPDATE SET default_limit = EXCLUDED.default_limit",
                limits_data
            )

        # Импортируем месячные бюджеты
        if data.get('monthly_budgets'):
            print("📅 Импортируем месячные бюджеты...")
            budgets_data = [(budg['month'], budg['category'], budg['budget_limit']) for budg in data['monthly_budgets']]
            execute_values(
                cursor,
                "INSERT INTO monthly_budgets (month, category, budget_limit) VALUES %s ON CONFLICT (month, category) DO UPDATE SET budget_limit = EXCLUDED.budget_limit",
                budgets_data
            )

        # Импортируем расходы
        if data.get('expenses'):
            print("📊 Импортируем расходы...")
            expenses_data = [
                (exp['id'], exp['category'], exp['amount'], exp['date'])
                for exp in data['expenses']
            ]
            execute_values(
                cursor,
                "INSERT INTO expenses (id, category, amount, date) VALUES %s ON CONFLICT (id) DO NOTHING",
                expenses_data
            )

        # Сохраняем изменения
        conn.commit()

        print("✅ Импорт завершен!")
        print(f"📊 Импортировано расходов: {len(data.get('expenses', []))}")
        print(f"💰 Импортировано лимитов категорий: {len(data.get('category_limits', []))}")
        print(f"📅 Импортировано месячных бюджетов: {len(data.get('monthly_budgets', []))}")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

    return True

if __name__ == "__main__":
    import_to_postgres()
