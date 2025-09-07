#!/usr/bin/env python3
"""
Скрипт для очистки БД от неправильных записей расходов.
Удаляет записи с командами бота и служебными сообщениями.
"""

import requests
import json
import os

API_BASE_URL = os.getenv("API_BASE_URL", "https://fastapi-production-eadf.up.railway.app")

def get_expenses(month: str):
    """Получить все расходы за месяц"""
    url = f"{API_BASE_URL}/expenses"
    response = requests.get(url, params={"month": month}, timeout=30)
    response.raise_for_status()
    return response.json()

def delete_expense(expense_id: int):
    """Удалить расход по ID"""
    url = f"{API_BASE_URL}/expenses/{expense_id}"
    response = requests.delete(url, timeout=30)
    response.raise_for_status()
    return response.status_code == 200

def is_bad_expense(category: str, amount: float) -> bool:
    """Проверить, является ли запись неправильной"""
    category_lower = category.lower()
    
    # Команды бота и служебные сообщения
    bad_patterns = [
        'setlimit', 'limits', 'month', 'report', 'help', 'start',
        '/', 'ok:', 'отчёт', 'привет', 'hello', 'твой user_id',
        'формат:', 'команды:', 'commands:', 'format:'
    ]
    
    # Проверяем категорию
    for pattern in bad_patterns:
        if pattern in category_lower:
            return True
    
    # Отрицательные или нулевые суммы
    if amount <= 0:
        return True
    
    # Слишком большие суммы (вероятно ошибка)
    if amount > 10000:
        return True
    
    return False

def cleanup_month(month: str, dry_run: bool = True):
    """Очистить расходы за месяц от неправильных записей"""
    print(f"🔍 Анализ расходов за {month}...")
    
    expenses = get_expenses(month)
    print(f"📊 Всего записей: {len(expenses)}")
    
    bad_expenses = []
    for expense in expenses:
        if is_bad_expense(expense['category'], expense['amount']):
            bad_expenses.append(expense)
    
    print(f"❌ Найдено неправильных записей: {len(bad_expenses)}")
    
    if bad_expenses:
        print("\n📋 Список записей для удаления:")
        for expense in bad_expenses:
            print(f"  ID {expense['id']}: {expense['category']} - ${expense['amount']} ({expense['date']})")
    
    if not dry_run and bad_expenses:
        print(f"\n🗑️  Удаляем {len(bad_expenses)} записей...")
        deleted_count = 0
        for expense in bad_expenses:
            if delete_expense(expense['id']):
                deleted_count += 1
                print(f"  ✅ Удален ID {expense['id']}")
            else:
                print(f"  ❌ Ошибка удаления ID {expense['id']}")
        
        print(f"\n✅ Удалено {deleted_count} из {len(bad_expenses)} записей")
    elif dry_run:
        print("\n🔍 Режим dry-run. Для удаления запустите с --apply")
    
    return len(bad_expenses)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Очистка БД от неправильных записей расходов")
    parser.add_argument("--month", default="2025-09", help="Месяц для очистки (YYYY-MM)")
    parser.add_argument("--apply", action="store_true", help="Применить изменения (иначе dry-run)")
    
    args = parser.parse_args()
    
    print(f"🧹 Очистка расходов за {args.month}")
    print(f"🌐 API: {API_BASE_URL}")
    print(f"🔧 Режим: {'ПРИМЕНЕНИЕ' if args.apply else 'DRY-RUN'}")
    print("-" * 50)
    
    bad_count = cleanup_month(args.month, dry_run=not args.apply)
    
    if bad_count > 0 and not args.apply:
        print(f"\n💡 Для удаления {bad_count} записей запустите:")
        print(f"   python cleanup_expenses.py --month {args.month} --apply")
    elif bad_count == 0:
        print("\n✅ Неправильных записей не найдено")

if __name__ == "__main__":
    main()
