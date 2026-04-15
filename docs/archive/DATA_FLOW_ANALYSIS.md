# Анализ связности данных в Budget Pet

## 📊 Текущая архитектура данных

### Источник данных: Единая PostgreSQL база данных

Все страницы используют **один источник данных** - PostgreSQL база данных через FastAPI backend.

```
┌─────────────────────────────────────────┐
│         PostgreSQL Database             │
├─────────────────────────────────────────┤
│  expenses          (расходы)            │
│  category_limits   (лимиты категорий)   │
│  monthly_budgets   (месячные бюджеты)   │
│  finance_loans     (займы)              │
│  finance_cards     (кредитные карты)    │
│  finance_payments  (платежи)            │
│  finance_income    (доходы)             │
└─────────────────────────────────────────┘
           │
           │ FastAPI REST API
           ▼
┌─────────────────────────────────────────┐
│         React Query Cache               │
│  (кэширование на клиенте)                │
└─────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────┐
│      Frontend Components                │
│  Dashboard | Expenses | Reports | ...   │
└─────────────────────────────────────────┘
```

---

## 🔗 Связи между страницами

### 1. Dashboard

**Использует:**
- `reportsApi.getReport(month)` → `/report?month=YYYY-MM`
  - **Источник:** Агрегированные данные из таблицы `expenses` + `monthly_budgets`
  - **Query Key:** `["report", month]`
  
- `financeApi.getSummary(month)` → `/api/finances/summary?month=YYYY-MM`
  - **Источник:** Данные из `finance_loans`, `finance_cards`, `finance_income`
  - **Query Key:** `["finance-summary", month]`

**Связь с другими страницами:**
- ✅ Использует те же данные, что и Reports (через `reportsApi.getReport`)
- ✅ Показывает расходы из таблицы `expenses`
- ✅ Показывает лимиты из `category_limits`
- ⚠️ **Не синхронизируется автоматически** при изменении расходов (только через React Query invalidation)

---

### 2. Expenses

**Использует:**
- `expensesApi.getAll(month, query)` → `/expenses?month=YYYY-MM&query=...`
  - **Источник:** Прямые данные из таблицы `expenses`
  - **Query Key:** `["expenses", month, query]`
  
- `limitsApi.getAll()` → `/limits`
  - **Источник:** Данные из `category_limits`
  - **Query Key:** `["limits"]`

**Связь с другими страницами:**
- ✅ **Прямая связь** с таблицей `expenses`
- ✅ При создании/обновлении/удалении расхода:
  ```typescript
  queryClient.invalidateQueries({ queryKey: ["expenses"] });
  queryClient.invalidateQueries({ queryKey: ["report"] });
  ```
  - Инвалидирует кэш расходов
  - Инвалидирует кэш отчетов (Dashboard и Reports обновятся)
- ✅ Использует категории из `category_limits` (синхронизировано с Categories)

---

### 3. Reports

**Использует:**
- `reportsApi.getReport(month, compare)` → `/report?month=YYYY-MM&compare=YYYY-MM`
  - **Источник:** Агрегированные данные из таблицы `expenses` + `monthly_budgets`
  - **Query Key:** `["report", month, compareMonth]`

**Связь с другими страницами:**
- ✅ **Использует те же данные, что Dashboard** (через `reportsApi.getReport`)
- ✅ Агрегирует данные из таблицы `expenses`
- ✅ Показывает лимиты из `monthly_budgets` и `category_limits`
- ✅ **Автоматически обновляется** при изменении расходов (через React Query invalidation)

---

### 4. Categories

**Использует:**
- `limitsApi.getAll()` → `/limits`
  - **Источник:** Данные из `category_limits`
  - **Query Key:** `["limits"]`

**Связь с другими страницами:**
- ✅ При создании/обновлении/удалении категории:
  ```typescript
  queryClient.invalidateQueries({ queryKey: ["limits"] });
  ```
  - Инвалидирует кэш лимитов
  - **НО:** Не инвалидирует `["report"]` и `["expenses"]`
  - ⚠️ **Проблема:** Dashboard и Reports могут показать устаревшие данные после изменения категории

---

### 5. Finances

**Использует:**
- `financeApi.getSummary(month)` → `/api/finances/summary?month=YYYY-MM`
  - **Источник:** `finance_loans`, `finance_cards`, `finance_income`
  - **Query Key:** `["finance-summary", month]`
  
- `financeApi.getLoans()`, `getCards()`, `getIncome()` и т.д.
  - **Источник:** Отдельные таблицы `finance_*`
  - **Query Keys:** Разные для каждого типа данных

**Связь с другими страницами:**
- ❌ **НЕ связан** с Expenses/Reports/Dashboard
- ✅ Использует отдельные таблицы БД
- ✅ Показывается на Dashboard только через `finance-summary`
- ⚠️ **Не синхронизируется** с остальными страницами

---

## 📋 Таблица связей данных

| Страница | Таблицы БД | API Endpoints | Query Keys | Синхронизация |
|----------|-----------|---------------|------------|---------------|
| **Dashboard** | `expenses`, `monthly_budgets`, `finance_*` | `/report`, `/api/finances/summary` | `["report"]`, `["finance-summary"]` | ✅ Через invalidation |
| **Expenses** | `expenses`, `category_limits` | `/expenses`, `/limits` | `["expenses"]`, `["limits"]` | ✅ Инвалидирует `["report"]` |
| **Reports** | `expenses`, `monthly_budgets` | `/report` | `["report"]` | ✅ Через invalidation |
| **Categories** | `category_limits`, `monthly_budgets` | `/limits` | `["limits"]` | ⚠️ Не инвалидирует `["report"]` |
| **Finances** | `finance_*` | `/api/finances/*` | `["finance-*"]` | ❌ Не связан |

---

## ⚠️ Проблемы текущей реализации

### 1. Categories не синхронизируется с Reports/Dashboard

**Проблема:**
```typescript
// В categories-page.tsx
queryClient.invalidateQueries({ queryKey: ["limits"] });
// НО не инвалидирует ["report"]
```

**Последствие:**
- При изменении лимита категории Dashboard и Reports показывают старые данные
- Нужно вручную обновить страницу или подождать автоматического refetch

**Решение:**
```typescript
// Добавить инвалидацию report
queryClient.invalidateQueries({ queryKey: ["limits"] });
queryClient.invalidateQueries({ queryKey: ["report"] }); // Добавить это
```

### 2. Finances полностью изолирован

**Проблема:**
- Finances использует отдельные таблицы
- Не влияет на Expenses/Reports
- Только Summary показывается на Dashboard

**Это нормально**, так как Finances - отдельный модуль (займы, карты, доходы).

### 3. Отсутствие глобальной синхронизации

**Проблема:**
- Каждая страница инвалидирует только свои query keys
- Нет централизованного механизма синхронизации

---

## ✅ Что работает хорошо

1. **Expenses ↔ Reports/Dashboard**
   - При добавлении расхода инвалидируются `["expenses"]` и `["report"]`
   - Все страницы обновляются автоматически

2. **Единый источник данных**
   - Все данные в одной PostgreSQL БД
   - Все запросы идут через FastAPI

3. **React Query кэширование**
   - Эффективное кэширование данных
   - Автоматический refetch при необходимости

---

## 🔮 Recurring Expenses: Как это повлияет?

### Предполагаемая реализация:

```typescript
// Новая таблица в БД
recurring_expenses (
  id, category, amount, frequency, 
  start_date, end_date, next_occurrence, ...
)

// API endpoint
POST /api/recurring-expenses
GET /api/recurring-expenses
```

### Как это будет работать:

1. **Создание рекуррентного расхода:**
   - Пользователь создает шаблон (например, "Netflix $15.99/месяц")
   - Сохраняется в `recurring_expenses`

2. **Автоматическое создание расходов:**
   - Cron job или scheduled task проверяет `next_occurrence`
   - Когда наступает дата, создается запись в таблице `expenses`
   - Используется тот же `add_expense()` что и для обычных расходов

3. **Влияние на другие страницы:**

   ✅ **Expenses:**
   - Автоматически появится новый расход в списке
   - Нужно инвалидировать `["expenses"]` после создания

   ✅ **Reports:**
   - Автоматически учтется в отчете (через таблицу `expenses`)
   - Нужно инвалидировать `["report"]` после создания

   ✅ **Dashboard:**
   - Автоматически обновится (через `["report"]`)
   - Покажет новый расход в метриках

   ✅ **Categories:**
   - Не изменится (использует те же категории)

### Необходимые изменения:

```typescript
// В функции создания рекуррентного расхода
const createRecurringExpenseMutation = useMutation({
  mutationFn: (recurring) => recurringExpensesApi.create(recurring),
  onSuccess: () => {
    // Инвалидировать все связанные кэши
    queryClient.invalidateQueries({ queryKey: ["recurring-expenses"] });
    queryClient.invalidateQueries({ queryKey: ["expenses"] }); // На будущее
    queryClient.invalidateQueries({ queryKey: ["report"] }); // На будущее
  },
});

// В scheduled task (backend)
async def process_recurring_expenses():
    # Найти рекуррентные расходы, которые нужно создать
    recurring = get_recurring_due_today()
    
    for item in recurring:
        # Создать расход в основной таблице
        add_expense(item.category, item.amount, today)
        
        # Обновить next_occurrence
        update_next_occurrence(item.id)
    
    # После создания расходов, фронтенд автоматически обновится
    # через React Query refetch (если страница открыта)
```

---

## 📊 Схема потока данных

### Текущий поток (Expenses):

```
User добавляет расход
    ↓
POST /expenses
    ↓
add_expense() → INSERT INTO expenses
    ↓
queryClient.invalidateQueries(["expenses", "report"])
    ↓
Dashboard обновляется (refetch ["report"])
Reports обновляется (refetch ["report"])
Expenses обновляется (refetch ["expenses"])
```

### Будущий поток (Recurring Expenses):

```
Scheduled task (cron)
    ↓
Находит recurring_expenses с next_occurrence = today
    ↓
Для каждого: add_expense() → INSERT INTO expenses
    ↓
(Фронтенд не знает об этом сразу)
    ↓
React Query автоматически refetch через refetchInterval
    ИЛИ
WebSocket/Polling для real-time обновления
    ↓
Dashboard/Reports/Expenses обновляются
```

---

## 🎯 Рекомендации

### 1. Исправить синхронизацию Categories

```typescript
// В categories-page.tsx, все мутации:
onSuccess: () => {
  queryClient.invalidateQueries({ queryKey: ["limits"] });
  queryClient.invalidateQueries({ queryKey: ["report"] }); // Добавить
  queryClient.invalidateQueries({ queryKey: ["expenses"] }); // Опционально
}
```

### 2. Добавить централизованную инвалидацию

```typescript
// utils/query-invalidation.ts
export function invalidateExpenseQueries(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: ["expenses"] });
  queryClient.invalidateQueries({ queryKey: ["report"] });
  queryClient.invalidateQueries({ queryKey: ["finance-summary"] }); // Если нужно
}

// Использование:
onSuccess: () => {
  invalidateExpenseQueries(queryClient);
}
```

### 3. Для Recurring Expenses

- Использовать ту же таблицу `expenses` для созданных расходов
- Добавить поле `recurring_expense_id` (опционально) для связи
- Инвалидировать те же query keys при создании
- Добавить polling или WebSocket для real-time обновлений

### 4. Добавить WebSocket/Polling (опционально)

Для real-time обновлений при создании рекуррентных расходов:

```typescript
// Polling каждые 30 секунд
useQuery({
  queryKey: ["expenses", month],
  queryFn: () => expensesApi.getAll(month),
  refetchInterval: 30000, // 30 секунд
});
```

---

## ✅ Выводы

### Текущее состояние:

1. ✅ **Единый источник данных** - все в PostgreSQL
2. ✅ **Expenses ↔ Reports/Dashboard** - хорошо синхронизированы
3. ⚠️ **Categories** - не синхронизируется с Reports
4. ❌ **Finances** - изолирован (это нормально)

### Recurring Expenses:

✅ **Будет работать автоматически** с Reports/Dashboard/Expenses, потому что:
- Использует ту же таблицу `expenses`
- Те же API endpoints
- Те же query keys для инвалидации

⚠️ **Нужно будет:**
- Инвалидировать `["expenses"]` и `["report"]` при создании
- Добавить polling или WebSocket для real-time обновлений
- Учесть в scheduled task инвалидацию кэшей

---

*Анализ выполнен на основе текущей кодовой базы*
