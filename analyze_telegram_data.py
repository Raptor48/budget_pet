#!/usr/bin/env python3
"""
Анализ данных из Telegram для сравнения с Railway БД
"""

import json
from datetime import datetime
from typing import List, Dict, Any
from collections import defaultdict

def load_telegram_expenses():
    """
    Загружает расходы из файла telegram_expenses.json.
    """
    try:
        with open('telegram_expenses.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Ошибка чтения telegram_expenses.json: {e}")
        return []

def analyze_telegram_data(expenses):
    """
    Анализирует данные из Telegram.
    """
    print("📊 Анализ данных из Telegram:")
    print(f"  Всего записей: {len(expenses)}")
    
    # Группировка по датам
    by_date = defaultdict(list)
    for exp in expenses:
        by_date[exp['date']].append(exp)
    
    print(f"  Уникальных дат: {len(by_date)}")
    print(f"  Даты: {sorted(by_date.keys())}")
    
    # Группировка по категориям
    by_category = defaultdict(list)
    for exp in expenses:
        by_category[exp['category']].append(exp)
    
    print(f"  Уникальных категорий: {len(by_category)}")
    print(f"  Категории: {sorted(by_category.keys())}")
    
    # Статистика по категориям
    print(f"\n📈 Статистика по категориям:")
    for category, exps in sorted(by_category.items()):
        total_amount = sum(exp['amount'] for exp in exps)
        print(f"  {category}: {len(exps)} записей, ${total_amount:.2f}")
    
    # Статистика по датам
    print(f"\n📅 Статистика по датам:")
    for date, exps in sorted(by_date.items()):
        total_amount = sum(exp['amount'] for exp in exps)
        print(f"  {date}: {len(exps)} записей, ${total_amount:.2f}")
    
    return {
        'by_date': dict(by_date),
        'by_category': dict(by_category),
        'total_records': len(expenses),
        'unique_dates': len(by_date),
        'unique_categories': len(by_category)
    }

def generate_summary_report(analysis):
    """
    Генерирует сводный отчет.
    """
    print(f"\n📋 Сводный отчет:")
    print(f"  📊 Всего записей: {analysis['total_records']}")
    print(f"  📅 Уникальных дат: {analysis['unique_dates']}")
    print(f"  🏷️ Уникальных категорий: {analysis['unique_categories']}")
    
    # Топ категории по количеству записей
    category_counts = {cat: len(exps) for cat, exps in analysis['by_category'].items()}
    top_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
    
    print(f"\n🏆 Топ категории по количеству записей:")
    for category, count in top_categories[:5]:
        print(f"  {category}: {count} записей")
    
    # Топ категории по сумме
    category_totals = {cat: sum(exp['amount'] for exp in exps) for cat, exps in analysis['by_category'].items()}
    top_totals = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    
    print(f"\n💰 Топ категории по сумме:")
    for category, total in top_totals[:5]:
        print(f"  {category}: ${total:.2f}")

def generate_railway_comparison_guide():
    """
    Генерирует инструкцию для сравнения с Railway БД.
    """
    print(f"\n🔍 Инструкция для сравнения с Railway БД:")
    print(f"  1. Подключитесь к Railway PostgreSQL БД")
    print(f"  2. Выполните запрос: SELECT category, amount, date FROM expenses ORDER BY date DESC;")
    print(f"  3. Сравните результаты с данными из telegram_expenses.json")
    print(f"  4. Обратите внимание на:")
    print(f"     - Количество записей по каждой категории")
    print(f"     - Суммы по каждой категории")
    print(f"     - Даты записей")
    print(f"     - Отсутствующие записи")

def main():
    """
    Основная функция анализа.
    """
    print("🔍 Анализ данных из Telegram...")
    
    # Загружаем данные
    expenses = load_telegram_expenses()
    
    if not expenses:
        print("❌ Не удалось загрузить данные из Telegram!")
        return
    
    # Анализируем
    analysis = analyze_telegram_data(expenses)
    
    # Генерируем отчет
    generate_summary_report(analysis)
    
    # Инструкция для сравнения
    generate_railway_comparison_guide()
    
    print(f"\n🎯 Анализ завершен!")
    print(f"📁 Файлы для сравнения:")
    print(f"  - telegram_expenses.json (JSON данные)")
    print(f"  - telegram_expenses.sql (SQL запросы)")

if __name__ == "__main__":
    main()
