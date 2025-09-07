#!/usr/bin/env python3
"""
Скрипт для сравнения данных из Telegram с Railway БД
"""

import json
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import List, Dict, Any, Set, Tuple
from collections import defaultdict

def get_railway_expenses():
    """
    Получает все расходы из PostgreSQL БД на Railway.
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL не установлен!")
        print("   Установите переменную окружения DATABASE_URL")
        print("   Пример: export DATABASE_URL='postgresql://user:pass@host:port/db'")
        return []
    
    try:
        print("🔌 Подключаемся к Railway PostgreSQL...")
        conn = psycopg2.connect(database_url)
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT id, category, amount, date 
                FROM expenses 
                ORDER BY date DESC, id DESC
            """)
            expenses = cursor.fetchall()
            
            # Конвертируем в список словарей
            result = []
            for row in expenses:
                result.append({
                    'id': row['id'],
                    'category': row['category'],
                    'amount': float(row['amount']),
                    'date': str(row['date'])
                })
            
            print(f"✅ Загружено {len(result)} записей из Railway БД")
            return result
    except Exception as e:
        print(f"❌ Ошибка подключения к Railway БД: {e}")
        print("   Проверьте DATABASE_URL и доступность БД")
        return []
    finally:
        if 'conn' in locals():
            conn.close()

def load_telegram_expenses():
    """
    Загружает расходы из файла telegram_expenses.json.
    """
    try:
        with open('telegram_expenses.json', 'r', encoding='utf-8') as f:
            expenses = json.load(f)
        print(f"✅ Загружено {len(expenses)} записей из Telegram")
        return expenses
    except Exception as e:
        print(f"❌ Ошибка чтения telegram_expenses.json: {e}")
        return []

def create_comparison_key(expense: Dict[str, Any]) -> str:
    """
    Создает ключ для сравнения записей.
    """
    return f"{expense['date']}_{expense['category']}_{expense['amount']}"

def compare_expenses(railway_expenses: List[Dict], telegram_expenses: List[Dict]) -> Dict[str, Any]:
    """
    Сравнивает расходы из Railway БД с Telegram данными.
    """
    print("\n🔍 Сравниваем данные...")
    
    # Создаем множества ключей для сравнения
    railway_keys = {create_comparison_key(exp) for exp in railway_expenses}
    telegram_keys = {create_comparison_key(exp) for exp in telegram_expenses}
    
    # Находим различия
    only_in_railway = railway_keys - telegram_keys
    only_in_telegram = telegram_keys - railway_keys
    common = railway_keys & telegram_keys
    
    print(f"📊 Результаты сравнения:")
    print(f"  ✅ Общие записи: {len(common)}")
    print(f"  🏠 Только в Railway: {len(only_in_railway)}")
    print(f"  📱 Только в Telegram: {len(only_in_telegram)}")
    
    return {
        'common': len(common),
        'only_railway': len(only_in_railway),
        'only_telegram': len(only_in_telegram),
        'only_railway_keys': only_in_railway,
        'only_telegram_keys': only_in_telegram,
        'common_keys': common
    }

def show_detailed_differences(railway_expenses: List[Dict], telegram_expenses: List[Dict], comparison: Dict):
    """
    Показывает детальные различия между базами.
    """
    print(f"\n📱 Записи только в Telegram (возможно отсутствуют в Railway):")
    if comparison['only_telegram'] > 0:
        for key in sorted(comparison['only_telegram_keys']):
            # Найдем запись по ключу
            for exp in telegram_expenses:
                if create_comparison_key(exp) == key:
                    print(f"  - {exp['date']} | {exp['category']} | ${exp['amount']:.2f} | {exp.get('raw_text', 'N/A')}")
                    break
    else:
        print("  (нет записей)")
    
    print(f"\n🏠 Записи только в Railway (возможно добавлены вручную):")
    if comparison['only_railway'] > 0:
        for key in sorted(comparison['only_railway_keys']):
            # Найдем запись по ключу
            for exp in railway_expenses:
                if create_comparison_key(exp) == key:
                    print(f"  - {exp['date']} | {exp['category']} | ${exp['amount']:.2f} | ID: {exp['id']}")
                    break
    else:
        print("  (нет записей)")

def analyze_categories(railway_expenses: List[Dict], telegram_expenses: List[Dict]):
    """
    Анализирует категории в обеих базах.
    """
    print(f"\n📊 Анализ категорий:")
    
    # Категории в Railway
    railway_categories = set(exp['category'] for exp in railway_expenses)
    print(f"  🏠 Railway категории ({len(railway_categories)}): {sorted(railway_categories)}")
    
    # Категории в Telegram
    telegram_categories = set(exp['category'] for exp in telegram_expenses)
    print(f"  📱 Telegram категории ({len(telegram_categories)}): {sorted(telegram_categories)}")
    
    # Различия
    only_railway_cats = railway_categories - telegram_categories
    only_telegram_cats = telegram_categories - railway_categories
    
    if only_railway_cats:
        print(f"  🏠 Только в Railway: {sorted(only_railway_cats)}")
    if only_telegram_cats:
        print(f"  📱 Только в Telegram: {sorted(only_telegram_cats)}")

def analyze_dates(railway_expenses: List[Dict], telegram_expenses: List[Dict]):
    """
    Анализирует даты в обеих базах.
    """
    print(f"\n📅 Анализ дат:")
    
    # Даты в Railway
    railway_dates = set(exp['date'] for exp in railway_expenses)
    print(f"  🏠 Railway даты ({len(railway_dates)}): {sorted(railway_dates)}")
    
    # Даты в Telegram
    telegram_dates = set(exp['date'] for exp in telegram_expenses)
    print(f"  📱 Telegram даты ({len(telegram_dates)}): {sorted(telegram_dates)}")
    
    # Различия
    only_railway_dates = railway_dates - telegram_dates
    only_telegram_dates = telegram_dates - railway_dates
    
    if only_railway_dates:
        print(f"  🏠 Только в Railway: {sorted(only_railway_dates)}")
    if only_telegram_dates:
        print(f"  📱 Только в Telegram: {sorted(only_telegram_dates)}")

def generate_missing_sql(telegram_expenses: List[Dict], missing_keys: Set[str]) -> str:
    """
    Генерирует SQL INSERT для отсутствующих записей.
    """
    if not missing_keys:
        return ""
    
    print(f"\n💾 Генерируем SQL для {len(missing_keys)} отсутствующих записей...")
    
    sql_statements = []
    for key in missing_keys:
        # Найдем запись по ключу
        for exp in telegram_expenses:
            if create_comparison_key(exp) == key:
                category = exp['category'].replace("'", "''")
                sql = f"INSERT INTO expenses (category, amount, date) VALUES ('{category}', {exp['amount']}, '{exp['date']}');"
                sql_statements.append(sql)
                break
    
    return '\n'.join(sql_statements)

def generate_summary_report(railway_expenses: List[Dict], telegram_expenses: List[Dict], comparison: Dict):
    """
    Генерирует сводный отчет.
    """
    print(f"\n📋 Сводный отчет:")
    print(f"  🏠 Railway БД: {len(railway_expenses)} записей")
    print(f"  📱 Telegram: {len(telegram_expenses)} записей")
    print(f"  ✅ Общие: {comparison['common']} записей")
    print(f"  🏠 Только в Railway: {comparison['only_railway']} записей")
    print(f"  📱 Только в Telegram: {comparison['only_telegram']} записей")
    
    # Процент совпадения
    total_unique = comparison['common'] + comparison['only_railway'] + comparison['only_telegram']
    if total_unique > 0:
        match_percentage = (comparison['common'] / total_unique) * 100
        print(f"  📊 Процент совпадения: {match_percentage:.1f}%")

def main():
    """
    Основная функция сравнения.
    """
    print("🔍 Сравнение Telegram данных с Railway БД...")
    
    # Загружаем данные
    railway_expenses = get_railway_expenses()
    telegram_expenses = load_telegram_expenses()
    
    if not railway_expenses:
        print("❌ Не удалось загрузить данные из Railway БД!")
        print("   Проверьте DATABASE_URL и доступность БД")
        return
    
    if not telegram_expenses:
        print("❌ Не удалось загрузить данные из Telegram!")
        return
    
    # Сравниваем
    comparison = compare_expenses(railway_expenses, telegram_expenses)
    
    # Показываем детальные различия
    show_detailed_differences(railway_expenses, telegram_expenses, comparison)
    
    # Анализируем категории и даты
    analyze_categories(railway_expenses, telegram_expenses)
    analyze_dates(railway_expenses, telegram_expenses)
    
    # Генерируем сводный отчет
    generate_summary_report(railway_expenses, telegram_expenses, comparison)
    
    # Генерируем SQL для отсутствующих записей
    if comparison['only_telegram'] > 0:
        missing_sql = generate_missing_sql(telegram_expenses, comparison['only_telegram_keys'])
        if missing_sql:
            with open('missing_expenses.sql', 'w', encoding='utf-8') as f:
                f.write(missing_sql)
            print(f"\n💾 SQL для отсутствующих записей сохранен в: missing_expenses.sql")
    
    print(f"\n🎯 Сравнение завершено!")

if __name__ == "__main__":
    main()
