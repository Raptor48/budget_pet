#!/usr/bin/env python3
"""
Скрипт для полной очистки всех расходов за сентябрь 2025
"""

import requests
import json

API_BASE_URL = "https://fastapi-production-eadf.up.railway.app"

def get_expenses(month):
    """Получить все расходы за месяц"""
    url = f"{API_BASE_URL}/expenses"
    response = requests.get(url, params={"month": month}, timeout=30)
    response.raise_for_status()
    return response.json()

def delete_expense(expense_id):
    """Удалить расход по ID"""
    url = f"{API_BASE_URL}/expenses/{expense_id}"
    response = requests.delete(url, timeout=30)
    response.raise_for_status()
    return response.status_code == 200

def clear_month(month):
    """Очистить все расходы за месяц"""
    print(f"🗑️  Очистка всех расходов за {month}...")
    
    expenses = get_expenses(month)
    print(f"📊 Найдено записей: {len(expenses)}")
    
    if not expenses:
        print("✅ Записей для удаления нет")
        return
    
    print("\n📋 Удаляем записи:")
    deleted_count = 0
    for expense in expenses:
        if delete_expense(expense['id']):
            deleted_count += 1
            print(f"  ✅ Удален ID {expense['id']}: {expense['category']} - ${expense['amount']}")
        else:
            print(f"  ❌ Ошибка удаления ID {expense['id']}")
    
    print(f"\n✅ Удалено {deleted_count} из {len(expenses)} записей")

if __name__ == "__main__":
    clear_month("2025-09")
