import sqlite3
import datetime
from typing import Optional, List, Tuple, Dict
from pathlib import Path
import math
# добавь рядом с остальными импортами
import os, sys
from pathlib import Path

APP_NAME = "BudgetApp"

def _user_data_dir() -> Path:
    # macOS
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    # Windows
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    # Linux/прочее
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path

# Разрешаем переопределить путь через переменную окружения при необходимости
DB_FILE = str(Path(os.environ.get("BUDGET_DB_PATH", str(_user_data_dir() / "budget.db"))).resolve())



# Safer connection for sync via Git/GitHub: avoid WAL side-files, keep short transactions

def _conn():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    # Disable WAL to avoid -wal/-shm side files in VCS; NORMAL is fine for desktop apps
    conn.execute("PRAGMA journal_mode=DELETE;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

# Helpers
############################

def _today_iso() -> str:
    return datetime.date.today().isoformat()


def _month_from_date(date_str: str) -> str:
    # date_str = YYYY-MM-DD -> YYYY-MM
    return date_str[:7]


def _prev_month(month_key: str) -> str:
    # month_key = YYYY-MM
    y, m = map(int, month_key.split("-"))
    if m == 1:
        return f"{y-1}-12"
    return f"{y:04d}-{m-1:02d}"


def _current_month() -> str:
    return _month_from_date(_today_iso())


# Helper to validate numeric amounts
def _validate_amount(value: float, what: str = "amount") -> float:
    """Ensure numeric, finite, and non-negative. Returns float or raises ValueError."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number")
    if not math.isfinite(v):
        raise ValueError(f"{what} must be a finite number")
    if v < 0:
        raise ValueError(f"{what} must be non-negative")
    return v

############################
# DB init
############################

def init_db():
    with _conn() as conn:
        c = conn.cursor()

        # Основные расходы
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                date TEXT NOT NULL
            )
            """
        )
        # Индексы для ускорения выборок
        c.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_expenses_cat_date ON expenses(category, date)")
        # Таблица дефолтных лимитов по категориям (редактируемая из GUI)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS category_limits (
                category TEXT PRIMARY KEY,
                default_limit REAL NOT NULL
            )
            """
        )
        # Таблица настроек (ключ-значение), сюда сохраним, например, платеж за квартиру
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        # Таблица месячных бюджетов с автопереносом
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_budgets (
                month TEXT NOT NULL,
                category TEXT NOT NULL,
                budget_limit REAL NOT NULL,
                rolled_over REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (month, category)
            )
            """
        )
        conn.commit()

############################
# Limits API (default per category)
############################

def set_limit(category: str, amount: float) -> None:
    """Установить дефолтный месячный лимит по категории (используется при инициализации месяца).
    Если запись есть — обновит, если нет — создаст.
    """
    amount = _validate_amount(amount, "limit")
    with _conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO category_limits(category, default_limit)
            VALUES(?, ?)
            ON CONFLICT(category) DO UPDATE SET default_limit=excluded.default_limit
            """,
            (category, amount),
        )
        conn.commit()


def get_limit(category: str) -> float:
    with _conn() as conn:
        c = conn.cursor()
        c.execute("SELECT default_limit FROM category_limits WHERE category=?", (category,))
        row = c.fetchone()
        return float(row[0]) if row else 0.0


def list_limits() -> List[Tuple[str, float]]:
    with _conn() as conn:
        c = conn.cursor()
        c.execute("SELECT category, default_limit FROM category_limits ORDER BY category")
        return [(r[0], float(r[1])) for r in c.fetchall()]


def set_limit_and_apply(category: str, amount: float, month: Optional[str] = None) -> None:
    """Установить дефолтный лимит и применить его к текущему месяцу (budget_limit = new_default + rolled_over)."""
    month = month or _current_month()
    set_limit(category, amount)
    with _conn() as conn:
        ensure_month_initialized(month)
        c = conn.cursor()
        c.execute(
            "SELECT rolled_over FROM monthly_budgets WHERE month=? AND category=?",
            (month, category),
        )
        row = c.fetchone()
        if row is None:
            return
        rolled = float(row[0])
        new_budget_total = float(amount) + rolled
        c.execute(
            "UPDATE monthly_budgets SET budget_limit=? WHERE month=? AND category=?",
            (new_budget_total, month, category),
        )
        conn.commit()


############################
# App settings (key-value)
############################

def set_setting(key: str, value) -> None:
    """Сохранить значение настройки по ключу. value хранится как TEXT (str),
    но можно передавать числа — они будут приведены к строке. """
    with _conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO settings(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(key), str(value)),
        )
        conn.commit()


def get_setting(key: str, default=None):
    """Получить значение настройки по ключу. Возвращает строку или default, если ключа нет.
    Попробуем привести к float, если это число."""
    with _conn() as conn:
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key=?", (str(key),))
        row = c.fetchone()
        if row is None:
            return default
        val = row[0]
        # попытка привести к float
        try:
            return float(val) if val is not None and val != "" else default
        except (ValueError, TypeError):
            return val


# Специализированные геттер/сеттер для платежа за квартиру
APARTMENT_PAYMENT_KEY = "apartment_payment"

def set_apartment_payment(amount: float) -> None:
    amount = _validate_amount(amount, "apartment payment")
    set_setting(APARTMENT_PAYMENT_KEY, amount)


def get_apartment_payment(default: float | None = None) -> Optional[float]:
    val = get_setting(APARTMENT_PAYMENT_KEY, default)
    try:
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return default

############################
# Monthly budget init & math
############################

def _get_month_budget(conn: sqlite3.Connection, month: str, category: str) -> Optional[Tuple[str, str, float, float]]:
    c = conn.cursor()
    c.execute(
        "SELECT month, category, budget_limit, rolled_over FROM monthly_budgets WHERE month=? AND category=?",
        (month, category),
    )
    return c.fetchone()


def _get_spent_for(conn: sqlite3.Connection, month: str, category: str) -> float:
    c = conn.cursor()
    month_prefix = month + "%"  # LIKE 'YYYY-MM%'
    c.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE category=? AND date LIKE ?",
        (category, month_prefix),
    )
    return float(c.fetchone()[0] or 0.0)


def ensure_month_initialized(month: Optional[str] = None) -> None:
    """Инициализирует бюджеты на указанный месяц для всех категорий из category_limits
    с учётом автопереноса остатка с прошлого месяца (только положительный остаток).
    Идемпотентно: повторный вызов ничего не сломает.
    """
    month = month or _current_month()
    with _conn() as conn:
        c = conn.cursor()
        limits = list_limits()
        if not limits:
            return  # нет категорий — инициализировать нечего
        prev_m = _prev_month(month)
        for category, default_limit in limits:
            # Если месяц уже создан — пропускаем
            if _get_month_budget(conn, month, category):
                continue
            # Остаток прошлого месяца (если прошлый месяц был инициализирован)
            prev_budget = _get_month_budget(conn, prev_m, category)
            leftover = 0.0
            if prev_budget:
                prev_limit_total = float(prev_budget[2])  # limit на прошлый месяц с учётом уже перенесённого ранее
                spent_prev = _get_spent_for(conn, prev_m, category)
                leftover = max(0.0, prev_limit_total - spent_prev)
            # Текущий лимит = дефолтный + положительный остаток
            current_limit = float(default_limit) + leftover
            c.execute(
                """
                INSERT INTO monthly_budgets(month, category, budget_limit, rolled_over)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(month, category) DO NOTHING
                """,
                (month, category, current_limit, leftover),
            )
        conn.commit()


def get_remaining(category: str, month: Optional[str] = None) -> float:
    month = month or _current_month()
    with _conn() as conn:
        ensure_month_initialized(month)
        budget_row = _get_month_budget(conn, month, category)
        total_budget = float(budget_row[2]) if budget_row else get_limit(category)
        spent = _get_spent_for(conn, month, category)
        return total_budget - spent


def get_month_report(month: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    month = month or _current_month()
    with _conn() as conn:
        ensure_month_initialized(month)
        result: Dict[str, Dict[str, float]] = {}
        for category, _ in list_limits():
            budget_row = _get_month_budget(conn, month, category)
            budget_total = float(budget_row[2]) if budget_row else get_limit(category)
            rolled = float(budget_row[3]) if budget_row else 0.0
            spent = _get_spent_for(conn, month, category)
            remaining = budget_total - spent
            result[category] = {
                "budget": budget_total,
                "spent": spent,
                "remaining": remaining,
                "rolled_over": rolled,
            }
        return result

############################
# Expenses CRUD (compatible with your GUI)
############################

def get_expenses() -> List[Tuple[int, str, float, str]]:
    with _conn() as conn:
        c = conn.cursor()
        c.execute("SELECT id, category, amount, date FROM expenses ORDER BY date DESC, id DESC")
        rows = c.fetchall()
        # Приводим amount к float, чтобы GUI и графики не спотыкались
        return [(int(r[0]), r[1], float(r[2]), r[3]) for r in rows]

# ---- Month-scoped helpers for UI ----

def get_expenses_for_month(month: str):
    """Вернуть расходы только за указанный месяц 'YYYY-MM'."""
    with _conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, category, amount, date FROM expenses WHERE date LIKE ? ORDER BY date DESC, id DESC",
            (month + "%",),
        )
        rows = c.fetchall()
        return [(int(r[0]), r[1], float(r[2]), r[3]) for r in rows]

def list_months():
    """Список месяцев, в которых есть записи расходов, формат 'YYYY-MM', по убыванию."""
    with _conn() as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT substr(date,1,7) AS m FROM expenses ORDER BY m DESC")
        return [r[0] for r in c.fetchall()]

def get_current_month() -> str:
    return _current_month()

def prev_month(month: str) -> str:
    return _prev_month(month)


def add_expense(category: str, amount: float, date: Optional[str] = None) -> Tuple[bool, float]:
    """Добавить расход. Возвращает кортеж (exceeded, remaining_after):
    - exceeded=True, если после добавления лимит на месяц ушёл в минус.
    - remaining_after — остаток по категории на месяц после добавления.
    """
    amount = _validate_amount(amount, "amount")
    date = date or _today_iso()
    month = _month_from_date(date)
    with _conn() as conn:
        ensure_month_initialized(month)
        c = conn.cursor()
        c.execute(
            "INSERT INTO expenses(category, amount, date) VALUES(?, ?, ?)",
            (category, amount, date),
        )
        conn.commit()
        remaining = get_remaining(category, month)
        exceeded = remaining < 0
        return exceeded, remaining


def update_expense(expense_id: int, category: str, amount: float) -> None:
    amount = _validate_amount(amount, "amount")
    with _conn() as conn:
        c = conn.cursor()
        c.execute("UPDATE expenses SET category=?, amount=? WHERE id=?", (category, amount, int(expense_id)))
        conn.commit()
# last 10 expenses
def get_recent_expenses(limit: int = 10):
    with _conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, category, amount, date FROM expenses ORDER BY date DESC, id DESC LIMIT ?",
            (int(limit),),
        )
        return [(int(r[0]), r[1], float(r[2]), r[3]) for r in c.fetchall()]
# Расходы по конкретной категории и месяцу
def get_expenses_by_category_month(category: str, month: str):
    with _conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, category, amount, date FROM expenses WHERE category=? AND date LIKE ? ORDER BY date DESC, id DESC",
            (category, month + "%"),
        )
        return [(int(r[0]), r[1], float(r[2]), r[3]) for r in c.fetchall()]

############################
# Back-compat simple API used earlier
############################

# Инициализация базы при импорте
init_db()