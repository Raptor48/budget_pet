# Список файлов для удаления

## ✅ Безопасно удалить (100%)

### Backup файлы (3 файла)
```
app.py.backup
bot.py.backup
bot_github.py.backup
```

### Миграционные скрипты (6 файлов)
```
create_postgres_tables.py
export_sqlite.py
import_postgres.py
fix_postgres_schema.py
execute_sql_auto.py
compare_telegram_vs_railway.py
```

### Аналитические скрипты (5 файлов)
```
analyze_telegram_data.py
parse_telegram_expenses.py
telegram_import.py
advanced_dead_code_analyzer.py
find_dead_code.py
```

### Временные данные (5 файлов)
```
telegram_expenses.json
telegram_expenses.sql
advanced_dead_code_report.json
dead_code_report.json
frontend/result.json
```

### Неиспользуемые файлы (2 файла)
```
bot_api.py
github_sync.py  # Корневой файл, есть services/github_sync.py
```

**Итого безопасно: 21 файл**

---

## ⚠️ Требует проверки

### Старый SQLite код
```
bd.py
```
**Используется в:**
- `base.py` (старый GUI)
- `ui/dialogs.py` (старый GUI)
- `services/logging_config.py` (только DB_FILE)
- `services/env_loader.py` (только DB_FILE)
- `web/deps.py` (только DB_FILE)

**Решение:** Удалить, если Desktop GUI не используется

### Старый GUI код
```
base.py
ui/ (вся директория)
app.py
services/bd_adapter.py
```
**Решение:** Удалить, если Desktop GUI не используется

### GitHub sync
```
services/github_sync.py
```
**Статус:** Импортируется в `web/deps.py`, но функция `get_github_sync()` не вызывается. В `web/main.py` GitHub sync отключен.

**Решение:** Удалить, если не используется

### SQLite БД
```
budget.db
```
**Решение:** Удалить, если не используется (все данные в PostgreSQL)

---

## 🚀 Быстрая очистка

### Вариант 1: Только безопасные файлы
```bash
./cleanup.sh
```

### Вариант 2: Полная очистка (если GUI не используется)
```bash
# Безопасные файлы
./cleanup.sh

# Старый GUI код
rm bd.py base.py app.py
rm -rf ui/
rm services/bd_adapter.py

# GitHub sync (если не используется)
rm services/github_sync.py
# И удалить импорт из web/deps.py

# SQLite БД
rm budget.db
```

---

## 📊 Статистика

- **Безопасно удалить:** 21 файл
- **Требует проверки:** ~8 файлов/директорий
- **Ожидаемое освобождение места:** ~500KB - 2MB

---

## ✅ Проверка после удаления

```bash
# Запустить тесты
pytest

# Проверить импорты
python3 -c "import web.main; print('OK')"
python3 -c "import bot; print('OK')"
```
