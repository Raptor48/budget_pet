#!/usr/bin/env python3
import requests

API_BASE_URL = "https://fastapi-production-eadf.up.railway.app"

def remove_test_expense():
    # Получить все расходы за сентябрь
    url = f"{API_BASE_URL}/expenses"
    response = requests.get(url, params={"month": "2025-09"}, timeout=30)
    response.raise_for_status()
    expenses = response.json()
    
    print(f"Всего записей за сентябрь: {len(expenses)}")
    
    # Найти и удалить тестовую запись
    for expense in expenses:
        if expense['category'] == 'Test':
            print(f"Найдена тестовая запись ID {expense['id']}: {expense['category']} - ${expense['amount']} ({expense['date']})")
            
            # Удалить запись
            delete_url = f"{API_BASE_URL}/expenses/{expense['id']}"
            delete_response = requests.delete(delete_url, timeout=30)
            
            if delete_response.status_code == 200:
                print("✅ Тестовая запись удалена")
            else:
                print(f"❌ Ошибка удаления: {delete_response.status_code}")
            return
    
    print("Тестовая запись не найдена")

if __name__ == "__main__":
    remove_test_expense()
