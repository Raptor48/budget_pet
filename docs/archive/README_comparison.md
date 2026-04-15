# Сравнение Telegram данных с Railway БД

## 📋 Описание

Скрипты для парсинга данных из Telegram и сравнения с текущей БД на Railway.

## 🔧 Установка зависимостей

```bash
python install_dependencies.py
```

## 📊 Парсинг данных из Telegram

```bash
python parse_telegram_expenses.py
```

**Результат:**
- `telegram_expenses.json` - JSON данные
- `telegram_expenses.sql` - SQL запросы для вставки

## 🔍 Сравнение с Railway БД

### 1. Установите DATABASE_URL

```bash
# Получите URL из Railway Dashboard
export DATABASE_URL='postgresql://postgres:password@host:port/railway'

# Или создайте .env файл
echo "DATABASE_URL=postgresql://postgres:password@host:port/railway" > .env
```

### 2. Запустите сравнение

```bash
python compare_telegram_vs_railway.py
```

## 📈 Что покажет сравнение

### ✅ Общие записи
- Записи, которые есть в обеих базах
- Процент совпадения

### 🏠 Только в Railway
- Записи, добавленные вручную в веб-интерфейсе
- Возможно, новые данные

### 📱 Только в Telegram
- Записи, отсутствующие в Railway БД
- Возможно, потерянные данные

### 📊 Анализ категорий и дат
- Сравнение категорий между базами
- Сравнение дат между базами

## 💾 Результаты

### Файлы:
- `telegram_expenses.json` - Данные из Telegram
- `telegram_expenses.sql` - SQL для вставки всех записей
- `missing_expenses.sql` - SQL для отсутствующих записей

### Статистика:
- Количество записей в каждой базе
- Процент совпадения
- Детальные различия

## 🚀 Пример использования

```bash
# 1. Парсим данные из Telegram
python parse_telegram_expenses.py

# 2. Устанавливаем DATABASE_URL
export DATABASE_URL='postgresql://postgres:password@host:port/railway'

# 3. Сравниваем с Railway БД
python compare_telegram_vs_railway.py

# 4. Анализируем результаты
python analyze_telegram_data.py
```

## ⚠️ Важно

- Убедитесь, что DATABASE_URL корректный
- Проверьте доступность Railway БД
- Сделайте бэкап перед массовыми изменениями
