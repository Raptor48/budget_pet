# Руководство по тестированию Budget Pet

## Быстрый старт

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Настройка тестовой базы данных

```bash
# Создать тестовую БД
createdb budget_pet_test

# Или через psql
psql -U postgres -c "CREATE DATABASE budget_pet_test;"
```

### 3. Установка переменной окружения (опционально)

```bash
export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/budget_pet_test"
```

### 4. Запуск тестов

```bash
# Все тесты
./run_tests.sh

# Или через pytest напрямую
pytest
```

## Что тестируется

### ✅ Финансовые расчеты

**Файл:** `tests/test_calculations.py`

Проверяет правильность расчетов:
- Месячная процентная ставка из APR
- Месячные проценты по займам и картам
- Графики погашения (сколько месяцев до полного погашения)
- Аналитика по счетам (экономия процентов, сэкономленное время)
- Средние платежи за последние N месяцев

**Примеры проверок:**
- $25,000 займ под 5.5% APR = ~$114.58 месячных процентов ✅
- $1,500 карта под 24.99% APR = ~$31.24 месячных процентов ✅
- График погашения учитывает проценты и платежи ✅

### ✅ Бюджетные расчеты

**Файл:** `tests/test_budget_calculations.py`

Проверяет:
- Установка лимитов категорий
- Расчет остатков после расходов
- Превышение лимитов
- Множественные расходы
- Отчеты по месяцам
- Перенос остатков между месяцами

**Примеры проверок:**
- Лимит $1,000, расход $250 → остаток $750 ✅
- Лимит $1,000, расход $1,200 → превышение, остаток -$200 ✅
- Положительный остаток переносится на следующий месяц ✅

### ✅ Финансовый репозиторий

**Файл:** `tests/test_finance_repo.py`

Проверяет CRUD операции:
- Создание/чтение/обновление/удаление займов
- Создание/чтение/обновление/удаление кредитных карт
- Создание платежей и автоматическое обновление балансов
- Создание доходов
- Фильтрация по месяцам и людям
- Генерация финансовых сводок

**Примеры проверок:**
- Платеж $1,000 уменьшает баланс займа с $25,000 до $24,000 ✅
- Платеж не может сделать баланс отрицательным (остается 0) ✅
- Сводка правильно суммирует доходы и долги ✅

### ✅ API Endpoints

**Файл:** `tests/test_api_endpoints.py`

Проверяет HTTP endpoints:
- Health check
- CRUD для расходов
- CRUD для лимитов
- Отчеты с сравнением месяцев
- Финансовые endpoints

**Примеры проверок:**
- GET /healthz возвращает {"ok": true} ✅
- POST /expenses создает расход ✅
- GET /report?month=2025-01&compare=2025-02 показывает процентное изменение ✅

## Запуск тестов

### Все тесты

```bash
pytest
```

### Конкретная категория

```bash
# Финансовые расчеты
./run_tests.sh --calculations

# Бюджетные расчеты
./run_tests.sh --budget

# Финансовый модуль
./run_tests.sh --finance

# API endpoints
./run_tests.sh --api
```

### С покрытием кода

```bash
./run_tests.sh --coverage

# Или напрямую
pytest --cov=web --cov=services --cov-report=html
```

### С подробным выводом

```bash
./run_tests.sh --verbose

# Или
pytest -v -s
```

## Интерпретация результатов

### ✅ Все тесты прошли

```
tests/test_calculations.py::TestMonthlyInterest::test_zero_apr PASSED
tests/test_calculations.py::TestMonthlyInterest::test_standard_loan PASSED
...
========== 45 passed in 2.34s ==========
```

**Значит:** Все расчеты работают правильно, цифры считаются корректно.

### ❌ Тесты не прошли

#### Ошибки в финансовых расчетах

```
FAILED tests/test_calculations.py::TestMonthlyInterest::test_standard_loan
AssertionError: assert 11458 == pytest.approx(11458, abs=1)
```

**Что проверить:**
1. Формула расчета месячной ставки: `APR / 100 / 12`
2. Округление до центов
3. Использование Decimal для точности

**Где искать:** `web/finance/calculations.py`

#### Ошибки в бюджетных расчетах

```
FAILED tests/test_budget_calculations.py::TestBudgetCalculations::test_add_expense_reduces_remaining
AssertionError: assert 750.0 == pytest.approx(750.0, rel=1e-6)
```

**Что проверить:**
1. Правильность SQL запросов
2. Формат дат (YYYY-MM-DD)
3. Логика переноса остатков

**Где искать:** `web/postgres_db.py`

#### Ошибки в репозитории

```
FAILED tests/test_finance_repo.py::TestPayments::test_create_payment_for_loan
AssertionError: assert 2400000 == 2400000
```

**Что проверить:**
1. Обновление балансов при платежах
2. Транзакции БД
3. Проверка на отрицательный баланс

**Где искать:** `web/finance/repo.py`

#### Ошибки в API

```
FAILED tests/test_api_endpoints.py::TestExpenses::test_create_expense
AssertionError: assert 200 == 500
```

**Что проверить:**
1. Валидация входных данных
2. Обработка ошибок
3. Подключение к БД

**Где искать:** `web/main.py`

## Отладка

### Просмотр SQL запросов

Добавьте в начало теста:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Проверка данных в БД

```bash
# Подключиться к тестовой БД
psql budget_pet_test

# Посмотреть расходы
SELECT * FROM expenses;

# Посмотреть займы
SELECT * FROM finance_loans;

# Посмотреть платежи
SELECT * FROM finance_payments;
```

### Запуск одного теста

```bash
pytest tests/test_calculations.py::TestMonthlyInterest::test_standard_loan -v -s
```

## Типичные проблемы

### 1. База данных не найдена

```
psycopg2.OperationalError: FATAL: database "budget_pet_test" does not exist
```

**Решение:**
```bash
createdb budget_pet_test
```

### 2. Нет прав доступа

```
psycopg2.OperationalError: FATAL: password authentication failed
```

**Решение:**
```bash
export TEST_DATABASE_URL="postgresql://postgres:ваш_пароль@localhost:5432/budget_pet_test"
```

### 3. Порт занят

```
psycopg2.OperationalError: could not connect to server
```

**Решение:** Проверьте, что PostgreSQL запущен:
```bash
pg_isready
```

### 4. Импорты не работают

```
ModuleNotFoundError: No module named 'web'
```

**Решение:** Запускайте из корневой директории проекта:
```bash
cd /path/to/budget_pet
pytest
```

## Добавление новых тестов

1. Создайте файл `test_<module>.py` в `tests/`
2. Импортируйте тестируемый модуль
3. Используйте fixtures из `conftest.py`
4. Следуйте naming: `test_<functionality>`

Пример:

```python
def test_calculate_interest():
    """Test that interest is calculated correctly."""
    result = calculate_monthly_interest(100000, Decimal("5.5"))
    assert result == pytest.approx(458, abs=1)
```

## CI/CD Integration

Тесты можно запускать автоматически при каждом коммите через GitHub Actions (см. `tests/README.md`).

## Следующие шаги

После того как все тесты пройдут:

1. ✅ Убедитесь, что расчеты правильные
2. ✅ Проверьте, что нет регрессий
3. ✅ Добавьте тесты для новых функций
4. ✅ Настройте автоматический запуск в CI/CD
