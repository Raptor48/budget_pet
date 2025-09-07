#!/usr/bin/env python3
import requests
import json

API_BASE_URL = "https://fastapi-production-eadf.up.railway.app"

def check_expenses(month):
    url = f"{API_BASE_URL}/expenses"
    response = requests.get(url, params={"month": month}, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    print(f"Всего записей за {month}: {len(data)}")
    print("\nВсе записи:")
    for item in data:
        print(f"ID {item['id']}: {item['category']} - ${item['amount']} ({item['date']})")

if __name__ == "__main__":
    check_expenses("2025-09")
