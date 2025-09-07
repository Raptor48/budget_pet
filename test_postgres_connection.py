import psycopg2
from urllib.parse import urlparse

def test_connection(name, database_url):
    """Тестирует подключение к PostgreSQL"""
    print(f"\n🧪 Тестируем {name}...")

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

        # Простой тест - получить версию PostgreSQL
        cursor.execute('SELECT version()')
        version = cursor.fetchone()

        print("✅ Подключение успешно!"        print(f"📊 PostgreSQL версия: {version[0][:50]}...")

        # Проверить таблицы
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = cursor.fetchall()

        print(f"📋 Найдено таблиц: {len(tables)}")
        if tables:
            print("📋 Список таблиц:")
            for table in tables:
                print(f"  - {table[0]}")

        cursor.close()
        conn.close()
        return True

    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return False

def main():
    print("🔗 Тестирование подключения к PostgreSQL\n")

    # Приватный URL (для Railway сервисов)
    private_url = "postgresql://postgres:qLyWBUAaVUsEIaQtfQmtMlsAWFyNJBIw@postgres.railway.internal:5432/railway"

    # Публичный URL (для локального доступа)
    public_url = "postgresql://postgres:qLyWBUAaVUsEIaQtfQmtMlsAWFyNJBIw@roundhouse.proxy.rlwy.net:44861/railway"

    # Тестируем приватное подключение
    private_ok = test_connection("ПРИВАТНОЕ подключение", private_url)

    # Тестируем публичное подключение
    public_ok = test_connection("ПУБЛИЧНОЕ подключение", public_url)

    print("
📊 РЕЗУЛЬТАТЫ:"    print(f"🔒 Приватное подключение: {'✅ Работает' if private_ok else '❌ Не работает'}")
    print(f"🌐 Публичное подключение: {'✅ Работает' if public_ok else '❌ Не работает'}")

    if private_ok and public_ok:
        print("\n🎉 Оба подключения работают! Готово к импорту данных.")
    elif public_ok:
        print("\n⚠️  Только публичное подключение работает. Используйте его для импорта.")
    else:
        print("\n❌ Проверьте URL и настройки PostgreSQL в Railway.")

if __name__ == "__main__":
    main()
