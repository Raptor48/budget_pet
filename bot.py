from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=True)
import os, re, logging
from datetime import datetime
# --- telegram imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler

# --- GitHub I/O (standalone for bot.py) --------------------------------------
import json, base64, time, sqlite3
from pathlib import Path
import requests
BOT_CURRENCY_SYMBOL = os.getenv("BOT_CURRENCY_SYMBOL", "$")

def _format_report_html(report, month):
    lines = [f"<b>Отчёт за {month}</b>", ""]
    max_cat_len = max(len(r[0]) for r in report)
    for category, spent, limit, remaining in report:
        limit_str = f"${limit:.2f}" if limit is not None else "—"
        lines.append(f"{category.ljust(max_cat_len)}  ${spent:.2f} / {limit_str}  Остаток: ${remaining:.2f}")
    return "<pre>" + "\n".join(lines) + "</pre>"

def _ensure_peers_table(db_path):
    """Ensure the peers table exists in the specified database."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS peers (
                    id INTEGER PRIMARY KEY,
                    username TEXT
                );
                """
            )
    except Exception as e:
        log.warning("Failed to ensure peers table: %s", e)

def _add_peer_if_new(db_path, user_id, username):
    """Add user to peers table if not already present."""
    _ensure_peers_table(db_path)
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute("SELECT 1 FROM peers WHERE id=?", (user_id,))
            if cur.fetchone() is None:
                conn.execute("INSERT INTO peers(id, username) VALUES (?, ?)", (user_id, username))
    except Exception as e:
        log.warning("Failed to add peer: %s", e)

def _get_peer_ids(db_path, exclude_id=None, allowed_ids=None):
    """Return list of peer ids, optionally excluding one and filtering by allowed_ids."""
    _ensure_peers_table(db_path)
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT id FROM peers").fetchall()
            ids = [row[0] for row in rows]
        if exclude_id is not None:
            ids = [i for i in ids if i != exclude_id]
        if allowed_ids is not None and len(allowed_ids) > 0:
            ids = [i for i in ids if i in allowed_ids]
        return ids
    except Exception as e:
        log.warning("Failed to get peer ids: %s", e)
        return []

# --- logging config (early, before any log.info) ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

log = logging.getLogger("tg-bot")
log.info("GH owner/repo: %s/%s, token_present=%s",
         os.getenv("GITHUB_OWNER"), os.getenv("GITHUB_REPO"),
         bool(os.getenv("GITHUB_TOKEN")))

# Переменные окружения (задать в Railway/локально)
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER  = os.getenv("GITHUB_OWNER")      # например: Raptor48
GITHUB_REPO   = os.getenv("GITHUB_REPO")       # например: budget_pet
GITHUB_DBPATH = os.getenv("GITHUB_DB_PATH", "budget.db")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

def _gh_api_url() -> str:
    if not (GITHUB_OWNER and GITHUB_REPO):
        raise RuntimeError("GITHUB_OWNER/GITHUB_REPO not set")
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_DBPATH}"

def _gh_headers():
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN not set")
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

def github_download_db(dest_path: str | Path) -> str | None:
    """Скачать budget.db из GitHub → dest_path. Вернуть sha (или None, если файла нет)."""
    dest = Path(dest_path)
    r = requests.get(_gh_api_url(), headers=_gh_headers(), params={"ref": GITHUB_BRANCH})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    content = base64.b64decode(data["content"]) if isinstance(data.get("content"), str) else b""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return data.get("sha")

def github_upload_db(src_path: str | Path, sha: str | None, message: str) -> str:
    """Загрузить файл на GitHub. Вернёт новый sha. При конфликте 409 — бросит RuntimeError."""
    src = Path(src_path)
    payload = {
        "message": message,
        "content": base64.b64encode(src.read_bytes()).decode(),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(_gh_api_url(), headers=_gh_headers(), data=json.dumps(payload))
    if r.status_code == 409:
        raise RuntimeError("409")
    r.raise_for_status()
    return r.json()["content"]["sha"]

# Обёртка «скачать→переключить БД→выполнить op→загрузить», с одним ретраем при 409
def with_github_db(commit_message: str):
    """
    Использование:
        @with_github_db("bot: add Food 50")
        def op():
            add_expense("Food", 50.0)
    """
    def decorator(op):
        def wrapper(*args, **kwargs):
            from bd import set_db_path, get_db_path, init_db  # set_db_path добавь в bd.py (см. ниже)
            tmp = Path("/tmp/budget.db") if os.name != "nt" else Path(os.getenv("TEMP","C:\\Temp")) / "budget.db"

            # 1) pull
            sha = github_download_db(tmp)
            set_db_path(str(tmp))  # переключаем bd.py на /tmp/budget.db
            init_db()              # на всякий случай (idempotent)

            # 2) выполнить операцию
            result = op(*args, **kwargs)

            # 3) push (с одной попыткой ретрая при конфликте)
            try:
                new_sha = github_upload_db(tmp, sha, commit_message)
            except RuntimeError as e:
                if "409" in str(e):  # кто-то успел обновить файл
                    # → качаем свежий и повторяем операцию заново
                    fresh_sha = github_download_db(tmp)
                    set_db_path(str(tmp))
                    init_db()
                    result = op(*args, **kwargs)
                    new_sha = github_upload_db(tmp, fresh_sha, commit_message + " (retry)")
                else:
                    raise
            return result
        return wrapper
    return decorator

# -------------------------------------------------------------------------------


def github_pull_set_db():
    """Pull the latest DB from GitHub to a temp path and switch bd.py to use it.
    Returns the sha of the pulled file (or None if not found).
    """
    from bd import set_db_path, init_db
    tmp = Path("/tmp/budget.db") if os.name != "nt" else Path(os.getenv("TEMP", "C:\\Temp")) / "budget.db"
    sha = github_download_db(tmp)
    set_db_path(str(tmp))
    init_db()
    return sha


# --- category usage (MRU/most-used sorting) ----------------------------------

def _current_db_path() -> str | None:
    try:
        from bd import get_db_path
        return get_db_path()
    except Exception:
        try:
            from bd import DB_FILE
            return DB_FILE
        except Exception:
            return None


def _record_category_use(cat: str):
    """Increment usage counter and update last_used_ts for a category in the current DB."""
    dbp = _current_db_path()
    if not dbp:
        return
    ts = int(time.time())
    try:
        with sqlite3.connect(dbp) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS category_usage (
                    category     TEXT PRIMARY KEY COLLATE NOCASE,
                    use_count    INTEGER NOT NULL DEFAULT 0,
                    last_used_ts INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            conn.execute(
                """
                INSERT INTO category_usage(category, use_count, last_used_ts)
                VALUES(?, 1, ?)
                ON CONFLICT(category) DO UPDATE SET
                    use_count    = use_count + 1,
                    last_used_ts = excluded.last_used_ts
                ;
                """,
                (cat, ts),
            )
    except Exception as e:
        log.warning("record_category_use failed: %s", e)


def _sort_categories_by_usage(cats: list[str]) -> list[str]:
    """Sort categories by last_used_ts DESC, then use_count DESC, then name ASC.
    If usage table absent/empty, returns input sorted alphabetically.
    """
    if not cats:
        return []
    dbp = _current_db_path()
    if not dbp:
        return sorted(cats, key=lambda x: x.lower())
    ranks = {}
    try:
        with sqlite3.connect(dbp) as conn:
            for c, cnt, ts in conn.execute(
                "SELECT category, use_count, last_used_ts FROM category_usage"
            ):
                ranks[c.lower()] = (int(ts or 0), int(cnt or 0))
    except Exception:
        return sorted(cats, key=lambda x: x.lower())

    def _key(name: str):
        ts, cnt = ranks.get(name.lower(), (0, 0))
        return (-ts, -cnt, name.lower())

    return sorted(cats, key=_key)


# --- budget threshold notifications (50% / 90%) ------------------------------

THRESHOLDS = (50, 90)


def _alerts_db_path() -> str | None:
    return _current_db_path()


def _ensure_alerts_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS budget_alerts (
            category     TEXT COLLATE NOCASE,
            month        TEXT,
            threshold    INTEGER,
            notified_ts  INTEGER NOT NULL,
            PRIMARY KEY (category, month, threshold)
        );
        """
    )


def _was_notified(cat: str, month: str, threshold: int) -> bool:
    dbp = _alerts_db_path()
    if not dbp:
        return False
    try:
        with sqlite3.connect(dbp) as conn:
            _ensure_alerts_table(conn)   # ← было _ensure_alerts_ta...ble(conn)
            cur = conn.execute(
                "SELECT 1 FROM budget_alerts WHERE category=? AND month=? AND threshold=?",
                (cat, month, threshold),
            )
            return cur.fetchone() is not None
    except Exception as e:
        log.warning("was_notified check failed: %s", e)
        return False


def _mark_notified(cat: str, month: str, threshold: int):
    dbp = _alerts_db_path()
    if not dbp:
        return
    ts = int(time.time())
    try:
        with sqlite3.connect(dbp) as conn:
            _ensure_alerts_table(conn)
            conn.execute(
                "INSERT OR REPLACE INTO budget_alerts(category, month, threshold, notified_ts) VALUES(?,?,?,?)",
                (cat, month, threshold, ts),
            )
    except Exception as e:
        log.warning("mark_notified failed: %s", e)


async def _maybe_notify_thresholds(update: Update, context: ContextTypes.DEFAULT_TYPE, cat: str):
    """Send a notice if cat has crossed 50% or 90% of its monthly budget and wasn't notified yet."""
    try:
        month = _current_month_for_user(context)
        report = get_month_report(month) or {}
        d = report.get(cat) or {}
        budget = float(d.get("budget", 0.0))
        spent = float(d.get("spent", 0.0))
        if budget <= 0:
            return  # нет лимита — нечего уведомлять
        ratio = spent / budget
        for th in THRESHOLDS:
            if ratio >= th / 100 and not _was_notified(cat, month, th):
                if th == 50:
                    txt = f"⚠️ {cat}: spend ⩾50% of limit!. Spent {spent:.2f} / {budget:.2f}."
                else:
                    txt = f"🔴 {cat}: spend ⩾90% of limit!!! Spent {spent:.2f} / {budget:.2f}."
                try:
                    await update.message.reply_text(txt)
                except Exception:
                    # fallback на chat_id
                    chat_id = update.effective_chat.id if update.effective_chat else None
                    if chat_id:
                        await context.bot.send_message(chat_id=chat_id, text=txt)
                _mark_notified(cat, month, th)
    except Exception as e:
        log.warning("maybe_notify failed: %s", e)


# --- импортируем твои функции из БД-модуля
from bd import (
    DB_FILE,
    add_expense,
    get_month_report,
    list_limits,
    set_limit,
    get_current_month,
)

# --- конфиг
TOKEN = os.getenv("TG_BOT_TOKEN") or ""
_raw_allowed = os.getenv("TG_ALLOWED_USER_IDS", "")
try:
    _ids = re.findall(r"\d+", _raw_allowed)
    ALLOWED = {int(x) for x in _ids}
except Exception:
    ALLOWED = set()
log = logging.getLogger("tg-bot")
log.info("Allowed users raw: %r", _raw_allowed)
log.info("Allowed users parsed: %s", sorted(ALLOWED))

def _allowed(user_id: int) -> bool:
    # если список пустой — пускаем всех; если не пустой — только перечисленных
    return (not ALLOWED) or (user_id in ALLOWED)

def _current_month_for_user(context: ContextTypes.DEFAULT_TYPE) -> str:
    # рабочий месяц сохраняем в user_data; по умолчанию текущий
    return context.user_data.get("month") or get_current_month()

def _find_category(user_input: str) -> str | None:
    """Возвращает каноническое имя категории по регистронезависимому совпадению."""
    try:
        cats = [name for name, _ in (list_limits() or [])]
    except Exception:
        cats = []
    lower_map = {c.lower(): c for c in cats}
    return lower_map.get(user_input.strip().lower())

def _build_main_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("Report (month)", callback_data="report")],

        [InlineKeyboardButton("➕ add expenses", callback_data="menu:add:0")],
    ]
    return InlineKeyboardMarkup(rows)

# --- categories menu with pagination ---
def _build_categories_keyboard(page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    """Inline-клавиатура для выбора категории с пагинацией. per_page = кол-во кнопок категорий."""
    try:
        cats_raw = [name for name, _ in (list_limits() or [])]
    except Exception:
        cats_raw = []
    cats = _sort_categories_by_usage(cats_raw)
    total = len(cats)
    start = max(0, page * per_page)
    end = min(total, start + per_page)
    page_cats = cats[start:end]

    rows = []
    # кладём по 2 кнопки в ряд
    for i in range(0, len(page_cats), 2):
        chunk = page_cats[i:i+2]
        rows.append([InlineKeyboardButton(c, callback_data=f"ask:{c}") for c in chunk])

    # навигация
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"menu:add:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"menu:add:{page+1}"))
    if nav:
        rows.append(nav)

    # назад в главное меню
    rows.append([InlineKeyboardButton("⬅️ back", callback_data="back:main")])

    # если категорий нет – сообщим об этом
    if not cats:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ back", callback_data="back:main")]
        ])

    return InlineKeyboardMarkup(rows)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    uid = update.effective_user.id
    uname = update.effective_user.full_name or ""
    # Всегда покажем user_id, чтобы человек мог прислать его администратору
    await update.message.reply_text(
        "Woof-Woof.\n"
        f"Your ID: {uid}\n\n"
        "type: /help, /report, /report <cat>, /setlimit <cat> <amt>, /limits, /month [YYYY-MM]"
    )
    # Добавить пользователя в peers, если нет
    dbp = _current_db_path()
    if dbp:
        _add_peer_if_new(dbp, uid, uname)
    if not _allowed(uid):
        return
    context.user_data["month"] = get_current_month()
    await update.message.reply_text(
        "Choose action:",
        reply_markup=_build_main_keyboard(),
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "Примеры:\n"
        "• food 50\n"
        "• yummy 120.5\n\n"
        "Команды:\n"
        "• /report — отчёт за текущий месяц\n"
        "• /report Food — отчёт по категории\n"
        "• /limits — список лимитов\n"
        "• /setlimit Food 30000 — задать лимит\n"
        "• /month — показать рабочий месяц\n"
        "• /month 2025-08 — выбрать другой месяц для отчётов\n",
    )

async def month_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    if context.args:
        val = context.args[0]
        if re.fullmatch(r"\d{4}-\d{2}", val):
            context.user_data["month"] = val
            await update.message.reply_text(f"Рабочий месяц: {val}")
        else:
            await update.message.reply_text("Используй формат YYYY-MM (например, 2025-08)")
    else:
        await update.message.reply_text(f"Рабочий месяц: {_current_month_for_user(context)}")

async def limits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    try:
        github_pull_set_db()
    except Exception as e:
        log.warning("github pull before limits failed: %s", e)
    try:
        pairs = list_limits() or []
    except Exception as e:
        log.error("list_limits failed: %s", e)
        pairs = []
    if not pairs:
        await update.message.reply_text("Лимиты не заданы.")
        return
    lines = [f"{name}: {float(limit):.2f}" for name, limit in pairs]
    await update.message.reply_text("Лимиты:\n" + "\n".join(lines))

async def setlimit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /setlimit <Category> <amount>")
        return
    cat_in = context.args[0]
    amt_in = context.args[1].replace(",", ".")
    cat = _find_category(cat_in)
    if not cat:
        await update.message.reply_text(f"Category '{cat_in}' not found. You can add it in desktop app (Settings → Add Category).")
        return
    try:
        amount = float(amt_in)
        month = _current_month_for_user(context)
        @with_github_db(f"bot: setlimit {cat} {amount:.2f}")
        def _op():
            from bd import set_limit_and_apply
            set_limit_and_apply(cat, amount, month)
        _op()
        await update.message.reply_text(f"Лимит для '{cat}' установлен: {amount:.2f}")
    except ValueError:
        await update.message.reply_text("Numbers only.")
    except Exception as e:
        log.error("set_limit failed: %s", e)
        await update.message.reply_text(f"Ошибка: {e}")

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    try:
        github_pull_set_db()
    except Exception as e:
        log.warning("github pull before report failed: %s", e)
    month = _current_month_for_user(context)
    report = get_month_report(month) or {}
    # /report <cat>
    if context.args:
        cat_in = " ".join(context.args)
        cat = _find_category(cat_in)
        if not cat:
            await update.message.reply_text(f"Category '{cat_in}' not found. You can add it in desktop app (Settings → Add Category).")
            return
        d = report.get(cat) or {}
        budget = float(d.get("budget", 0.0))
        spent = float(d.get("spent", 0.0))
        rem = float(d.get("remaining", 0.0))
        rolled = float(d.get("rolled_over", 0.0))
        await update.message.reply_text(
            f"[{month}] {cat}\n"
            f"Budget:  {budget:.2f}\n"
            f"Spent:   {spent:.2f}\n"
            f"Remain:  {rem:.2f}\n"
            f"Rolled:  {rolled:.2f}"
        )
        return

    # Общий отчёт
    if not report:
        await update.message.reply_text(f"[{month}] данных нет.")
        return
    lines = [f"[{month}] Summary:"]
    total_b, total_s = 0.0, 0.0
    for cat, d in sorted(report.items()):
        b = float(d.get("budget", 0.0))
        s = float(d.get("spent", 0.0))
        r = float(d.get("remaining", 0.0))
        lines.append(f"• {cat}: spent {s:.2f} / budget {b:.2f} → rem {r:.2f}")
        total_b += b; total_s += s
    lines.append(f"Final: spent {total_s:.2f} / budget {total_b:.2f}")
    await update.message.reply_text("\n".join(lines))

async def on_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    if not _allowed(update.effective_user.id):
        return
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    if data.startswith("menu:add"):
        # форматы: "menu:add" или "menu:add:<page>"
        try:
            parts = data.split(":")
            page = int(parts[2]) if len(parts) > 2 else 0
        except Exception:
            page = 0
        try:
            github_pull_set_db()
        except Exception as e:
            log.warning("github pull before menu(add) failed: %s", e)
        await q.edit_message_text("Выберите категорию:", reply_markup=_build_categories_keyboard(page))
        return

    if data == "back:main":
        await q.edit_message_text("Выбери действие:", reply_markup=_build_main_keyboard())
        return

    if data == "report":
        try:
            github_pull_set_db()
        except Exception as e:
            log.warning("github pull before report(btn) failed: %s", e)
        month = _current_month_for_user(context)
        report = get_month_report(month) or {}
        if not report:
            await q.edit_message_text(f"[{month}] данных нет.")
            return
        lines = [f"[{month}] Отчёт:"]
        total_b, total_s = 0.0, 0.0
        for cat, d in sorted(report.items()):
            b = float(d.get("budget", 0.0))
            s = float(d.get("spent", 0.0))
            r = float(d.get("remaining", 0.0))
            lines.append(f"• {cat}: spent {s:.2f} / budget {b:.2f} → rem {r:.2f}")
            total_b += b; total_s += s
        lines.append(f"ИТОГО: spent {total_s:.2f} / budget {total_b:.2f}")
        await q.edit_message_text("\n".join(lines), reply_markup=_build_main_keyboard())
        return

    if data == "limits":
        try:
            github_pull_set_db()
        except Exception as e:
            log.warning("github pull before limits(btn) failed: %s", e)
        pairs = list_limits() or []
        txt = "Лимиты не заданы." if not pairs else "Лимиты:\n" + "\n".join(f"{c}: {float(v):.2f}" for c, v in pairs)
        await q.edit_message_text(txt, reply_markup=_build_main_keyboard())
        return

    if data.startswith("ask:"):
        cat = data.split(":", 1)[1]
        # запоминаем, что ждём сумму для этой категории
        context.user_data["await_amount_for"] = cat
        await q.edit_message_text(
            f"Введите сумму для категории '{cat}' (например, 123.45).",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data="cancel")]
            ])
        )
        return

    if data == "cancel":
        # сбрасываем ожидание суммы
        context.user_data.pop("await_amount_for", None)
        await q.edit_message_text("Выбери действие:", reply_markup=_build_main_keyboard())
        return



    # по умолчанию — просто восстановим клавиатуру
    await q.edit_message_text("Выбери действие:", reply_markup=_build_main_keyboard())

FREE_TEXT_RE = re.compile(r"^(?P<cat>[A-Za-zА-Яа-яЁё][\w &\\-]+)\s+(?P<amt>\d+(?:[.,]\d+)?)$")

async def text_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # гарантируем свежую БД перед проверкой категории
    try:
        github_pull_set_db()
    except Exception as e:
        log.warning("github pull before text_add failed: %s", e)
    if not _allowed(update.effective_user.id):
        return
    text = (update.message.text or "").strip()
    # режим ввода только суммы после нажатия кнопки "…"
    pending_cat = context.user_data.get("await_amount_for")
    dbp = _current_db_path()
    sender_id = update.effective_user.id if update.effective_user else None
    sender_name = update.effective_user.full_name if update.effective_user else "Someone"
    currency_symbol = BOT_CURRENCY_SYMBOL
    allowed_ids = ALLOWED if len(ALLOWED) > 0 else None
    if pending_cat:
        amt_txt = text.replace(",", ".")
        try:
            amount = float(amt_txt)
        except ValueError:
            await update.message.reply_text("Введите число, например 123.45 или 123,45. Или нажмите Отмена.")
            return
        try:
            @with_github_db(f"bot: add {pending_cat} {amount:.2f}")
            def _op():
                from bd import add_expense
                res = add_expense(pending_cat, amount)
                _record_category_use(pending_cat)
                return res
            exceeded, remaining = _op()
            context.user_data.pop("await_amount_for", None)
            msg = f"OK: {pending_cat} +{amount:.2f}"
            if exceeded:
                msg += f" — Warning: off limit. Remaining: {remaining:.2f}"
            # уведомления о порогах 50%/90%
            await _maybe_notify_thresholds(update, context, pending_cat)
            await update.message.reply_text(msg, reply_markup=_build_main_keyboard())
            # Рассылка другим пользователям
            if dbp and sender_id is not None:
                # Добавить отправителя в peers (на всякий случай)
                _add_peer_if_new(dbp, sender_id, sender_name)
                peer_ids = _get_peer_ids(dbp, exclude_id=sender_id, allowed_ids=allowed_ids)
                # Fallback: если peers пуст, но ALLOWED задан — шлём всем из ALLOWED, кроме отправителя
                if not peer_ids and allowed_ids:
                    peer_ids = [i for i in allowed_ids if i != sender_id]
                notify_msg = f"{sender_name} added {pending_cat} {currency_symbol}{amount:.2f}"
                for peer_id in peer_ids:
                    try:
                        await context.bot.send_message(chat_id=peer_id, text=notify_msg)
                    except Exception as e:
                        log.warning("Failed to send notify to %s: %s", peer_id, e)
        except Exception as e:
            log.error("add_expense (custom amount) failed: %s", e)
            await update.message.reply_text(f"Ошибка: {e}")
        return

    m = FREE_TEXT_RE.match(text)
    if not m:
        await update.message.reply_text("Формат: <category> <amount> (например, food 50)")
        return
    cat_in = m.group("cat")
    amt_in = m.group("amt").replace(",", ".")
    cat = _find_category(cat_in)
    if not cat:
        await update.message.reply_text(f"Category '{cat_in}' not found. You can add it in desktop app (Settings → Add Category).")
        return
    try:
        amount = float(amt_in)
    except ValueError:
        await update.message.reply_text("Numbers only.")
        return

    try:
        @with_github_db(f"bot: add {cat} {amount:.2f}")
        def _op():
            from bd import add_expense
            res = add_expense(cat, amount)
            _record_category_use(cat)
            return res
        exceeded, remaining = _op()
        msg = f"OK: {cat} +{amount:.2f}"
        if exceeded:
            msg += f" — Warning: off limit. Remaining: {remaining:.2f}"
        # уведомления о порогах 50%/90%
        await _maybe_notify_thresholds(update, context, cat)
        await update.message.reply_text(msg)
        # Рассылка другим пользователям
        if dbp and sender_id is not None:
            # Добавить отправителя в peers (на всякий случай)
            _add_peer_if_new(dbp, sender_id, sender_name)
            peer_ids = _get_peer_ids(dbp, exclude_id=sender_id, allowed_ids=allowed_ids)
            notify_msg = f"{sender_name} added {cat} {currency_symbol}{amount:.2f}"
            for peer_id in peer_ids:
                try:
                    await context.bot.send_message(chat_id=peer_id, text=notify_msg)
                except Exception as e:
                    log.warning("Failed to send notify to %s: %s", peer_id, e)
    except Exception as e:
        log.error("add_expense via GitHub failed: %s", e)
        await update.message.reply_text(f"Ошибка: {e}")
        return



if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("month", month_cmd))
    app.add_handler(CommandHandler("limits", limits_cmd))
    app.add_handler(CommandHandler("setlimit", setlimit_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CallbackQueryHandler(on_btn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_add))

    log.info("Starting bot, DB: %s", DB_FILE)
    log.info("GH owner/repo: %s/%s, token_present=%s", os.getenv("GITHUB_OWNER"), os.getenv("GITHUB_REPO"), bool(os.getenv("GITHUB_TOKEN")))
    # один раз подтянем БД при старте
    try:
        github_pull_set_db()
        log.info("Initial GitHub DB pull: OK")
    except Exception as e:
        log.warning("Initial GitHub DB pull failed: %s", e)
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        poll_interval=0,  # без паузы между циклами
        timeout=200  # long-poll: держим соединение до 60с
    )