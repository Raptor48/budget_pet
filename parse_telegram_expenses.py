#!/usr/bin/env python3
"""
Парсер для извлечения расходов из Telegram chat history (result.json)
Создает файл с расходами в формате, совместимом с PostgreSQL БД на Railway
"""

import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
import os

def parse_expense_message(text: str) -> Optional[Dict[str, Any]]:
    """
    Парсит сообщение с расходом и извлекает категорию и сумму.
    
    Поддерживаемые форматы:
    - "food 25" -> category: "Food", amount: 25.0
    - "transport 15.50" -> category: "Transport", amount: 15.50
    - "beer and snacks 100" -> category: "Beer and Snacks", amount: 100.0
    - "3d 50" -> category: "3D", amount: 50.0
    - "pharmacy 25.99" -> category: "Pharmacy", amount: 25.99
    """
    if not isinstance(text, str):
        return None
    
    # Убираем лишние пробелы и приводим к нижнему регистру
    text = text.strip().lower()
    
    # Исключаем только системные команды, но НЕ сообщения бота с расходами
    if any(cmd in text for cmd in ['/start', '/help', '/limits', '/report', 'отчёт:', 'итого:', 'добавлено', 'добавлен']):
        return None
    
    # Специальная обработка для сообщений бота: "OK: Beer and Snacks +12.00"
    if text.startswith('ok:') and '+' in text:
        # Извлекаем категорию и сумму из формата "ok: category +amount"
        ok_pattern = r'ok:\s+([a-zA-Z0-9\s&,]+?)\s+\+(\d+(?:\.\d+)?)'
        ok_match = re.match(ok_pattern, text)
        if ok_match:
            category_raw = ok_match.group(1).strip()
            amount_str = ok_match.group(2)
        else:
            return None
    else:
        # Обычный паттерн: категория + сумма
        # Поддерживает: "food 25", "beer and snacks 100", "3d 50", "pharmacy 25.99"
        pattern = r'^([a-zA-Z0-9\s&,]+?)\s+(\d+(?:\.\d+)?)$'
        match = re.match(pattern, text)
        
        if not match:
            return None
        
        category_raw = match.group(1).strip()
        amount_str = match.group(2)
    
    try:
        amount = float(amount_str)
    except ValueError:
        return None
    
    # Нормализуем название категории
    category = normalize_category(category_raw)
    
    return {
        'category': category,
        'amount': amount,
        'raw_text': text
    }

def normalize_category(category: str) -> str:
    """
    Нормализует название категории к стандартному формату.
    """
    # Убираем лишние пробелы и приводим к правильному регистру
    category = category.strip().title()
    
    # Маппинг известных категорий (расширенный список)
    category_mapping = {
        'Food': 'Food',
        'Pood': 'Food',  # Исправляем опечатку
        'Transport': 'Transport', 
        'Entertainment': 'Entertainment',
        'Beer And Snacks': 'Beer and Snacks',
        'Beer & Snacks': 'Beer and Snacks',
        'Beer And Snack': 'Beer and Snacks',
        'Cloth': 'Cloth',
        'Clothes': 'Cloth',
        'Fun': 'Fun',
        'Internet, Mobile': 'Internet, Mobile',
        'Internet Mobile': 'Internet, Mobile',
        'Loan & Credit Cards': 'Loan & Credit Cards',
        'Loan Credit Cards': 'Loan & Credit Cards',
        'Pharmacy': 'Pharmacy',
        'Smoking': 'Smoking',
        'Subscriptions': 'Subscriptions',
        'Travel': 'Travel',
        'Utilities': 'Utilities',
        'Yummy': 'Yummy',
        '3D': '3D',
        '3d': '3D',
        'Test': 'Test',
        'Health': 'Health',
        'Education': 'Education',
        'Shopping': 'Shopping',
        'Gifts': 'Gifts',
        'Insurance': 'Insurance',
        'Maintenance': 'Maintenance',
        'Other': 'Other'
    }
    
    return category_mapping.get(category, category)

def parse_telegram_json(file_path: str) -> List[Dict[str, Any]]:
    """
    Парсит result.json и извлекает все расходы.
    """
    expenses = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Ошибка чтения файла {file_path}: {e}")
        return []
    
    messages = data.get('messages', [])
    print(f"Найдено сообщений: {len(messages)}")
    
    for message in messages:
        # Проверяем, что это сообщение от пользователя
        if message.get('type') != 'message':
            continue
            
        # НЕ пропускаем сообщения от бота - они могут содержать расходы!
        # if message.get('from') == 'Family Budget Bot':
        #     continue
            
        text = message.get('text', '')
        
        # Обрабатываем разные форматы text
        if isinstance(text, list):
            # Если text - массив объектов, извлекаем plain text
            plain_texts = []
            for item in text:
                if isinstance(item, dict) and item.get('type') == 'plain':
                    plain_texts.append(item.get('text', ''))
            text = ' '.join(plain_texts)
        elif isinstance(text, str):
            text = text
        else:
            continue
        
        # Парсим сообщение на предмет расходов
        expense = parse_expense_message(text)
        if expense:
            # Добавляем метаданные
            expense.update({
                'message_id': message.get('id'),
                'date': message.get('date'),
                'date_unixtime': message.get('date_unixtime'),
                'from': message.get('from'),
                'from_id': message.get('from_id')
            })
            expenses.append(expense)
    
    return expenses

def format_for_database(expenses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Форматирует расходы для вставки в PostgreSQL БД Railway.
    Формат: id (SERIAL), category (TEXT), amount (REAL), date (TEXT)
    """
    formatted_expenses = []
    
    for expense in expenses:
        # Парсим дату
        date_str = expense.get('date', '')
        try:
            # Парсим ISO формат: "2025-08-11T15:12:09"
            if 'T' in date_str:
                parsed_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                # Конвертируем в формат YYYY-MM-DD для БД
                db_date = parsed_date.strftime('%Y-%m-%d')
            else:
                db_date = date_str
        except Exception as e:
            print(f"Ошибка парсинга даты '{date_str}': {e}")
            continue
        
        # Формат для PostgreSQL БД Railway
        formatted_expense = {
            'category': expense['category'],
            'amount': float(expense['amount']),
            'date': db_date,
            # Дополнительные поля для анализа
            'raw_text': expense['raw_text'],
            'message_id': expense.get('message_id'),
            'from_user': expense.get('from'),
            'original_date': expense.get('date'),
            'source': 'telegram_import'
        }
        
        formatted_expenses.append(formatted_expense)
    
    return formatted_expenses

def save_expenses_to_file(expenses: List[Dict[str, Any]], output_file: str):
    """
    Сохраняет расходы в JSON файл.
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(expenses, f, ensure_ascii=False, indent=2)
        print(f"Сохранено {len(expenses)} расходов в файл: {output_file}")
    except Exception as e:
        print(f"Ошибка сохранения файла {output_file}: {e}")

def generate_sql_inserts(expenses: List[Dict[str, Any]]) -> str:
    """
    Генерирует SQL INSERT запросы для вставки в PostgreSQL Railway.
    Формат таблицы: id (SERIAL), category (TEXT), amount (REAL), date (TEXT)
    """
    sql_statements = []
    
    for expense in expenses:
        # Экранируем кавычки в названии категории
        category = expense['category'].replace("'", "''")
        raw_text = expense['raw_text'].replace("'", "''")
        
        sql = f"""INSERT INTO expenses (category, amount, date) 
VALUES ('{category}', {expense['amount']}, '{expense['date']}');"""
        sql_statements.append(sql)
    
    return '\n'.join(sql_statements)

def main():
    """
    Основная функция парсера.
    """
    input_file = 'frontend/result.json'
    output_file = 'telegram_expenses.json'
    sql_file = 'telegram_expenses.sql'
    
    print("🔍 Парсинг Telegram chat history...")
    
    # Парсим JSON
    expenses = parse_telegram_json(input_file)
    print(f"📊 Найдено расходов: {len(expenses)}")
    
    if not expenses:
        print("❌ Расходы не найдены!")
        return
    
    # Форматируем для БД
    formatted_expenses = format_for_database(expenses)
    print(f"✅ Отформатировано для БД: {len(formatted_expenses)}")
    
    # Сохраняем в JSON
    save_expenses_to_file(formatted_expenses, output_file)
    
    # Генерируем SQL
    sql_inserts = generate_sql_inserts(formatted_expenses)
    with open(sql_file, 'w', encoding='utf-8') as f:
        f.write(sql_inserts)
    print(f"💾 SQL запросы сохранены в: {sql_file}")
    
    # Статистика по категориям
    category_stats = {}
    for expense in formatted_expenses:
        category = expense['category']
        amount = expense['amount']
        if category not in category_stats:
            category_stats[category] = {'count': 0, 'total': 0.0}
        category_stats[category]['count'] += 1
        category_stats[category]['total'] += amount
    
    print("\n📈 Статистика по категориям:")
    for category, stats in sorted(category_stats.items()):
        print(f"  {category}: {stats['count']} записей, ${stats['total']:.2f}")
    
    print(f"\n🎯 Готово! Проверьте файлы:")
    print(f"  - {output_file} (JSON формат)")
    print(f"  - {sql_file} (SQL запросы)")

if __name__ == "__main__":
    main()
