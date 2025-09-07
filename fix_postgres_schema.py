#!/usr/bin/env python3
"""
Fix PostgreSQL schema to add AUTO_INCREMENT to expenses.id
"""
import os
import psycopg2
from urllib.parse import urlparse

def fix_schema():
    """Fix the expenses table schema."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL not set")
        return
    
    # Parse the URL
    parsed = urlparse(database_url)
    
    # Connect to PostgreSQL
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path[1:]  # убираем слэш
    )
    
    cursor = conn.cursor()
    
    try:
        print("🔧 Исправляем схему таблицы expenses...")
        
        # Check current schema
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = 'expenses' AND column_name = 'id'
        """)
        result = cursor.fetchone()
        
        if result:
            print(f"Текущая схема id: {result}")
            
            # Check if it's already SERIAL
            if 'nextval' in str(result[3]):
                print("✅ Поле id уже имеет AUTO_INCREMENT")
                return
        
        # Create a new table with correct schema
        print("📊 Создаем новую таблицу expenses_new...")
        cursor.execute("""
            CREATE TABLE expenses_new (
                id SERIAL PRIMARY KEY,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                date TEXT NOT NULL
            )
        """)
        
        # Copy data from old table
        print("📋 Копируем данные...")
        cursor.execute("""
            INSERT INTO expenses_new (category, amount, date)
            SELECT category, amount, date FROM expenses
        """)
        
        # Drop old table and rename new one
        print("🗑️ Удаляем старую таблицу...")
        cursor.execute("DROP TABLE expenses")
        
        print("🔄 Переименовываем новую таблицу...")
        cursor.execute("ALTER TABLE expenses_new RENAME TO expenses")
        
        # Commit changes
        conn.commit()
        print("✅ Схема исправлена успешно!")
        
        # Verify the fix
        cursor.execute("SELECT COUNT(*) FROM expenses")
        count = cursor.fetchone()[0]
        print(f"📊 Записей в таблице: {count}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    fix_schema()
