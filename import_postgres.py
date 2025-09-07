import json
import os
from urllib.parse import urlparse
import psycopg2
from psycopg2.extras import execute_values

def import_to_postgres():
    """Импортирует данные в PostgreSQL"""

    # ВСТАВЬТЕ СВОЮ СТРОКУ ПОДКЛЮЧЕНИЯ ИЗ RAILWAY ЗДЕСЬ:
    database_url = "postgresql://username:password@host:port/database"

    # Получите эту строку из Railway dashboard → PostgreSQL → Variables → DATABASE_URL

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

        # Импортируем бюджеты
        if data.get('limits'):
            print("💰 Импортируем бюджеты...")
            limits_data = [(lim['category'], lim['amount']) for lim in data['limits']]
            execute_values(
                cursor,
                "INSERT INTO limits (category, amount) VALUES %s ON CONFLICT (category) DO UPDATE SET amount = EXCLUDED.amount",
                limits_data
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
        print(f"💰 Импортировано бюджетов: {len(data.get('limits', []))}")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

    return True

if __name__ == "__main__":
    import_to_postgres()
