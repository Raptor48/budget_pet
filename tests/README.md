# Тесты для Budget Pet

## Структура тестов

```
tests/
├── __init__.py
├── conftest.py              # Pytest конфигурация и fixtures
├── test_calculations.py     # Тесты финансовых расчетов (проценты, графики погашения)
├── test_budget_calculations.py  # Тесты бюджетных расчетов (остатки, переносы)
├── test_finance_repo.py     # Тесты финансового репозитория (loans, cards, payments)
└── test_api_endpoints.py    # Тесты API endpoints
```

## Установка зависимостей

```bash
pip install -r requirements.txt
```

## Настройка тестовой базы данных

Создайте тестовую базу данных PostgreSQL:

```bash
# Создать базу данных
createdb budget_pet_test

# Или через psql
psql -U postgres -c "CREATE DATABASE budget_pet_test;"
```

Установите переменную окружения:

```bash
export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/budget_pet_test"
```

Или создайте файл `.env.test`:

```
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/budget_pet_test
```

## Запуск тестов

### Запустить все тесты

```bash
pytest
```

### Запустить конкретный файл тестов

```bash
pytest tests/test_calculations.py
```

### Запустить конкретный тест

```bash
pytest tests/test_calculations.py::TestMonthlyInterest::test_zero_apr
```

### Запустить с покрытием кода

```bash
pytest --cov=web --cov=services --cov-report=html
```

### Запустить только unit тесты

```bash
pytest -m unit
```

### Запустить только integration тесты

```bash
pytest -m integration
```

### Запустить с подробным выводом

```bash
pytest -v
```

### Запустить с выводом print statements

```bash
pytest -s
```

## Что тестируется

### 1. Финансовые расчеты (`test_calculations.py`)

- ✅ Расчет месячной процентной ставки из APR
- ✅ Расчет месячных процентов
- ✅ Расчет графиков погашения (payoff schedules)
- ✅ Расчет аналитики по счетам
- ✅ Расчет средних платежей
- ✅ Генерация сводки по процентам

**Примеры проверок:**
- $25,000 займ под 5.5% APR = ~$114.58 месячных процентов
- $1,500 кредитная карта под 24.99% APR = ~$31.24 месячных процентов
- График погашения учитывает проценты и платежи

### 2. Бюджетные расчеты (`test_budget_calculations.py`)

- ✅ Установка лимитов категорий
- ✅ Расчет остатков бюджета
- ✅ Добавление расходов и уменьшение остатка
- ✅ Превышение лимитов
- ✅ Множественные расходы в одной категории
- ✅ Отчеты по месяцам
- ✅ Перенос остатков между месяцами (rollover)

**Примеры проверок:**
- Лимит $1,000, расход $250 → остаток $750
- Лимит $1,000, расход $1,200 → превышение, остаток -$200
- Положительный остаток переносится на следующий месяц

### 3. Финансовый репозиторий (`test_finance_repo.py`)

- ✅ CRUD операции для займов (loans)
- ✅ CRUD операции для кредитных карт (cards)
- ✅ Создание платежей и обновление балансов
- ✅ Создание доходов (income)
- ✅ Фильтрация по месяцам и людям
- ✅ Генерация финансовых сводок

**Примеры проверок:**
- Создание займа обновляет баланс
- Платеж уменьшает баланс счета
- Платеж не может сделать баланс отрицательным
- Сводка правильно суммирует доходы и долги

### 4. API Endpoints (`test_api_endpoints.py`)

- ✅ Health check endpoint
- ✅ CRUD для расходов (expenses)
- ✅ CRUD для лимитов (limits)
- ✅ Отчеты (reports) с сравнением месяцев
- ✅ Финансовые endpoints (loans, cards, payments)

**Примеры проверок:**
- GET /healthz возвращает {"ok": true}
- POST /expenses создает расход
- GET /report возвращает правильные данные
- Сравнение месяцев показывает процентное изменение

## Интерпретация результатов

### ✅ Все тесты прошли
Все работает корректно, расчеты правильные.

### ❌ Тесты не прошли

**Если тесты расчетов не проходят:**
- Проверьте логику в `web/finance/calculations.py`
- Проверьте округление (используется Decimal для точности)
- Проверьте формулы расчета процентов

**Если тесты бюджета не проходят:**
- Проверьте логику в `web/postgres_db.py`
- Проверьте работу с датами (форматы YYYY-MM-DD)
- Проверьте перенос остатков между месяцами

**Если тесты репозитория не проходят:**
- Проверьте подключение к БД
- Проверьте SQL запросы в `web/finance/repo.py`
- Проверьте обновление балансов при платежах

**Если тесты API не проходят:**
- Проверьте endpoints в `web/main.py`
- Проверьте валидацию данных (Pydantic models)
- Проверьте обработку ошибок

## Отладка

### Просмотр SQL запросов

Добавьте логирование в тесты:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Проверка данных в БД

```bash
psql budget_pet_test -c "SELECT * FROM expenses;"
psql budget_pet_test -c "SELECT * FROM finance_loans;"
```

### Запуск одного теста с отладкой

```bash
pytest tests/test_calculations.py::TestMonthlyInterest::test_standard_loan -s -v
```

## CI/CD Integration

Тесты можно интегрировать в GitHub Actions:

```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pytest
        env:
          TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/budget_pet_test
```

## Покрытие кода

Цель: покрыть критичные компоненты на 80%+

```bash
# Генерация отчета
pytest --cov=web --cov=services --cov-report=html

# Просмотр отчета
open htmlcov/index.html
```

## Добавление новых тестов

1. Создайте файл `test_<module>.py` в директории `tests/`
2. Импортируйте необходимые модули
3. Используйте fixtures из `conftest.py`
4. Следуйте naming convention: `test_<functionality>`
5. Добавьте docstrings для описания тестов

Пример:

```python
def test_calculate_interest():
    """Test that interest is calculated correctly."""
    result = calculate_monthly_interest(100000, Decimal("5.5"))
    assert result == pytest.approx(458, abs=1)
```
