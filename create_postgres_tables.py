import psycopg2
from urllib.parse import urlparse

def create_tables():
    """Создает таблицы в PostgreSQL базе данных"""
    
    # Публичный URL для локального доступа
    database_url = "postgresql://postgres:qLyWBUAaVUsEIaQtfQmtMlsAWFyNJBIw@ballast.proxy.rlwy.net:41763/railway"
    
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
        
        print("📊 Создаем таблицу expenses...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                date TEXT NOT NULL
            )
        """)
        
        print("💰 Создаем таблицу category_limits...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS category_limits (
                category TEXT PRIMARY KEY,
                default_limit REAL NOT NULL
            )
        """)
        
        print("📅 Создаем таблицу monthly_budgets...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monthly_budgets (
                month TEXT NOT NULL,
                category TEXT NOT NULL,
                budget_limit REAL NOT NULL,
                rolled_over REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (month, category)
            )
        """)
        
        print("⚙️ Создаем таблицу settings...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        
        print("📈 Создаем таблицу category_usage...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS category_usage (
                category TEXT PRIMARY KEY COLLATE "C",
                use_count INTEGER NOT NULL DEFAULT 0,
                last_used_ts INTEGER NOT NULL DEFAULT 0
            )
        """)
        
        print("🔍 Создаем индексы...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenses_cat_date ON expenses(category, date)")
        
        # Сохраняем изменения
        conn.commit()
        
        print("✅ Все таблицы созданы успешно!")
        
        # Проверяем созданные таблицы
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """)
        tables = cursor.fetchall()
        
        print(f"📋 Созданные таблицы ({len(tables)}):")
        for table in tables:
            print(f"  - {table[0]}")
        
        cursor.close()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка создания таблиц: {e}")
        return False

if __name__ == "__main__":
    create_tables()
