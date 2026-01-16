# Отчет о связности данных в Budget Pet

## 📊 Краткий ответ

### ✅ Да, данные связаны и используют один источник

**Все страницы используют одну PostgreSQL базу данных через FastAPI backend.**

---

## 🔗 Детальная схема связей

### Источник данных: PostgreSQL

```
PostgreSQL Database
├── expenses          ← Dashboard, Expenses, Reports
├── category_limits   ← Categories, Expenses, Dashboard, Reports
├── monthly_budgets   ← Dashboard, Reports
├── finance_loans     ← Finances, Dashboard (summary)
├── finance_cards     ← Finances, Dashboard (summary)
├── finance_payments  ← Finances
└── finance_income    ← Finances, Dashboard (summary)
```

---

## 📋 Связи между страницами

### 1. Dashboard ↔ Expenses ↔ Reports

**✅ ХОРОШО СВЯЗАНЫ**

```
Expenses (добавляет расход)
    ↓
INSERT INTO expenses
    ↓
invalidateQueries(["expenses", "report"])
    ↓
Dashboard обновляется ✅
Reports обновляется ✅
Expenses обновляется ✅
```

**Как это работает:**
- Expenses использует: `GET /expenses` → таблица `expenses`
- Reports использует: `GET /report` → агрегирует из `expenses`
- Dashboard использует: `GET /report` → те же данные, что Reports

**Код:**
```typescript
// expenses-page.tsx
onSuccess: () => {
  queryClient.invalidateQueries({ queryKey: ["expenses"] });
  queryClient.invalidateQueries({ queryKey: ["report"] }); // ✅
}
```

---

### 2. Categories ↔ Dashboard/Reports

**⚠️ ЧАСТИЧНО СВЯЗАНЫ (есть проблема)**

```
Categories (изменяет лимит)
    ↓
UPDATE category_limits
    ↓
invalidateQueries(["limits"])
    ↓
Expenses обновляется ✅ (использует limits)
Dashboard НЕ обновляется ⚠️ (использует report)
Reports НЕ обновляется ⚠️ (использует report)
```

**Проблема:**
```typescript
// categories-page.tsx
onSuccess: () => {
  queryClient.invalidateQueries({ queryKey: ["limits"] }); // ✅
  // ❌ НЕТ: queryClient.invalidateQueries({ queryKey: ["report"] });
}
```

**Последствие:**
- При изменении лимита категории Dashboard и Reports показывают старые данные
- Нужно вручную обновить страницу

**Решение:**
```typescript
// Исправить в categories-page.tsx
onSuccess: () => {
  queryClient.invalidateQueries({ queryKey: ["limits"] });
  queryClient.invalidateQueries({ queryKey: ["report"] }); // Добавить
}
```

---

### 3. Finances ↔ Dashboard

**✅ СВЯЗАНЫ (только Summary)**

```
Finances (добавляет платеж/доход)
    ↓
UPDATE finance_* tables
    ↓
loadData() (локальная перезагрузка)
    ↓
Dashboard обновляется ✅ (через finance-summary)
Expenses/Reports НЕ обновляются (это нормально)
```

**Как это работает:**
- Finances использует отдельные таблицы `finance_*`
- Dashboard показывает только Summary через `GET /api/finances/summary`
- Не влияет на Expenses/Reports (это отдельный модуль)

---

## 🎯 Recurring Expenses: Будет ли работать?

### ✅ ДА, будет автоматически работать!

**Почему:**

1. **Использует ту же таблицу `expenses`:**
   ```
   Recurring Expenses (scheduled task)
       ↓
   add_expense() → INSERT INTO expenses
       ↓
   Та же таблица, что и обычные расходы
   ```

2. **Те же API endpoints:**
   - `GET /expenses` - покажет рекуррентные расходы
   - `GET /report` - учтет их в отчете

3. **Автоматическая синхронизация:**
   ```typescript
   // При создании рекуррентного расхода (scheduled task)
   add_expense(category, amount, date)
       ↓
   // Фронтенд автоматически обновится через:
   // 1. React Query refetchInterval
   // 2. Или инвалидацию кэшей
   ```

### Что нужно сделать:

1. **В scheduled task (backend):**
   ```python
   # После создания расходов из recurring_expenses
   # Кэши автоматически обновятся через refetchInterval
   # Или можно добавить WebSocket/Polling
   ```

2. **На фронтенде:**
   ```typescript
   // Добавить refetchInterval для real-time обновлений
   useQuery({
     queryKey: ["expenses", month],
     queryFn: () => expensesApi.getAll(month),
     refetchInterval: 30000, // Проверять каждые 30 сек
   });
   ```

3. **Инвалидация кэшей (если нужно принудительное обновление):**
   ```typescript
   // После создания рекуррентного расхода
   queryClient.invalidateQueries({ queryKey: ["expenses"] });
   queryClient.invalidateQueries({ queryKey: ["report"] });
   ```

---

## 📊 Визуальная схема потока данных

### Текущий поток (Expenses):

```
┌─────────────┐
│   Expenses  │
│   (страница) │
└──────┬──────┘
       │ POST /expenses
       ▼
┌─────────────┐
│  FastAPI    │
│  Backend    │
└──────┬──────┘
       │ INSERT INTO expenses
       ▼
┌─────────────┐
│ PostgreSQL  │
│  expenses   │
└──────┬──────┘
       │
       ├──► GET /expenses → Expenses страница
       ├──► GET /report → Dashboard
       └──► GET /report → Reports
       
       После изменения:
       invalidateQueries(["expenses", "report"])
       → Все страницы обновляются ✅
```

### Будущий поток (Recurring Expenses):

```
┌──────────────────┐
│ Scheduled Task   │
│ (cron/scheduler) │
└────────┬─────────┘
         │ Проверяет recurring_expenses
         │ next_occurrence = today
         ▼
┌──────────────────┐
│  FastAPI         │
│  add_expense()   │
└────────┬─────────┘
         │ INSERT INTO expenses
         ▼
┌──────────────────┐
│ PostgreSQL       │
│  expenses        │
└────────┬─────────┘
         │
         ├──► GET /expenses → Expenses (обновится через refetch)
         ├──► GET /report → Dashboard (обновится через refetch)
         └──► GET /report → Reports (обновится через refetch)
```

---

## ✅ Выводы

### Текущее состояние:

1. **✅ Expenses ↔ Reports ↔ Dashboard** - отлично связаны
   - Используют одну таблицу `expenses`
   - Автоматически синхронизируются через React Query

2. **⚠️ Categories** - частично связаны
   - Использует `category_limits` (те же данные)
   - НО не инвалидирует `["report"]` при изменении
   - **Нужно исправить**

3. **✅ Finances** - связан с Dashboard (через summary)
   - Использует отдельные таблицы (это нормально)
   - Не влияет на Expenses/Reports (это отдельный модуль)

### Recurring Expenses:

**✅ Будет работать автоматически**, потому что:

1. Использует ту же таблицу `expenses`
2. Те же API endpoints (`/expenses`, `/report`)
3. Те же query keys для инвалидации
4. React Query автоматически обновит все страницы

**Что нужно добавить:**
- RefetchInterval для real-time обновлений
- Или WebSocket/Polling для мгновенных обновлений
- Инвалидацию кэшей при создании (опционально)

---

## 🔧 Рекомендации по улучшению

### 1. Исправить Categories синхронизацию

```typescript
// frontend/src/components/categories/categories-page.tsx

// Во всех мутациях добавить:
onSuccess: () => {
  queryClient.invalidateQueries({ queryKey: ["limits"] });
  queryClient.invalidateQueries({ queryKey: ["report"] }); // Добавить
}
```

### 2. Добавить централизованную инвалидацию

```typescript
// frontend/src/lib/query-invalidation.ts
export function invalidateExpenseRelatedQueries(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: ["expenses"] });
  queryClient.invalidateQueries({ queryKey: ["report"] });
}

export function invalidateCategoryRelatedQueries(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: ["limits"] });
  queryClient.invalidateQueries({ queryKey: ["report"] });
  queryClient.invalidateQueries({ queryKey: ["expenses"] });
}
```

### 3. Для Recurring Expenses

```typescript
// Добавить refetchInterval для real-time обновлений
useQuery({
  queryKey: ["expenses", month],
  queryFn: () => expensesApi.getAll(month),
  refetchInterval: 30000, // 30 секунд
});
```

---

**Итог:** Данные хорошо связаны, но есть одна проблема с Categories, которую легко исправить. Recurring Expenses будет работать автоматически с остальными страницами.
