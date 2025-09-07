#!/usr/bin/env python3
"""
Автоматическое выполнение SQL запросов из telegram_expenses.sql в Railway БД
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor

def execute_telegram_sql():
    """
    Выполняет SQL запросы из telegram_expenses.sql в Railway БД.
    """
    # Получаем DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL не установлен!")
        print("   Установите: export DATABASE_URL='postgresql://postgres:пароль@хост:порт/railway'")
        return False
    
    # Скрываем пароль для безопасности
    safe_url = database_url.split('@')[1] if '@' in database_url else database_url
    print(f"✅ Подключаемся к: postgresql://***@{safe_url}")
    
    try:
        # Читаем SQL файл
        with open('telegram_expenses.sql', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Разделяем на отдельные запросы
        queries = [q.strip() for q in content.split(';') if q.strip()]
        print(f"📊 Загружено {len(queries)} SQL запросов")
        
        # Подключаемся к БД
        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        
        with conn.cursor() as cursor:
            print(f"🚀 Выполняем {len(queries)} запросов...")
            
            success_count = 0
            error_count = 0
            
            for i, query in enumerate(queries, 1):
                try:
                    cursor.execute(query)
                    success_count += 1
                    if i % 10 == 0:
                        print(f"  ✅ {i}/{len(queries)} запросов выполнено")
                except Exception as e:
                    error_count += 1
                    print(f"  ❌ Ошибка в запросе {i}: {str(e)[:100]}...")
            
            print(f"\n📈 Результаты:")
            print(f"  ✅ Успешно: {success_count} запросов")
            print(f"  ❌ Ошибок: {error_count} запросов")
            
            if success_count > 0:
                print(f"  🎯 {success_count} записей добавлено в БД")
            
            # Проверяем общее количество записей
            cursor.execute("SELECT COUNT(*) FROM expenses")
            total_count = cursor.fetchone()[0]
            print(f"  📊 Всего записей в БД: {total_count}")
            
            # Показываем последние записи
            cursor.execute("""
                SELECT category, amount, date 
                FROM expenses 
                ORDER BY id DESC 
                LIMIT 3
            """)
            recent = cursor.fetchall()
            
            print(f"  📋 Последние записи:")
            for record in recent:
                print(f"    - {record[2]} | {record[0]} | ${record[1]:.2f}")
    
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()
    
    return True

def main():
    """
    Основная функция.
    """
    print("🚀 Автоматическое выполнение SQL запросов в Railway БД...")
    
    if execute_telegram_sql():
        print("\n✅ Готово! Проверьте веб-интерфейс для очистки дубликатов")
    else:
        print("\n❌ Ошибка выполнения")

if __name__ == "__main__":
    main()
