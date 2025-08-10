import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from bd import (get_expenses_for_month, add_expense,
                update_expense, set_limit_and_apply, set_limit, get_remaining,
                get_month_report, delete_expense, list_months, list_limits, get_current_month,
                prev_month, get_apartment_payment, set_apartment_payment, delete_category)
import matplotlib.pyplot as plt
import os, json, base64
import requests
import atexit
import sys
from pathlib import Path
from datetime import datetime
# --- Additional imports for new features ---
import shutil
from io import BytesIO
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
try:
    from dotenv import load_dotenv, find_dotenv
    def _load_env_multi():
        # 1) Текущая рабочая папка
        load_dotenv()
        # 2) Папка исполняемого файла (.exe/.app)
        try:
            if getattr(sys, "frozen", False):
                exe_dir = Path(sys.executable).resolve().parent
                load_dotenv(exe_dir / ".env")
        except Exception:
            pass
        # 3) Папка рядом с локальной БД (AppData / Application Support)
        try:
            from bd import DB_FILE
            load_dotenv(Path(DB_FILE).resolve().parent / ".env")
        except Exception:
            pass
        # 4) Поиск «вверх»
        try:
            env_path = find_dotenv(usecwd=True)
            if env_path:
                load_dotenv(env_path)
        except Exception:
            pass
    _load_env_multi()
except Exception:
    pass

from bd import DB_FILE

# --- Logging setup (console + file) ---
import logging
LOG_FILE = Path(DB_FILE).with_name("app.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ],
)
logger = logging.getLogger("budget")

# --- GitHub API sync helpers (works in exe/app) ---
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER  = os.getenv("GITHUB_OWNER")
GITHUB_REPO   = os.getenv("GITHUB_REPO")
GITHUB_DBPATH = os.getenv("GITHUB_DB_PATH", "budget.db")  # path in repo
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

_GH_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_DBPATH}"
    if GITHUB_OWNER and GITHUB_REPO else None
)

def _gh_headers():
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set")
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

def github_download_db(dest_path: Path) -> str | None:
    """Download budget.db from GitHub to dest_path. Return SHA (or None if file not found)."""
    logger.info("GitHub: downloading DB from %s", _GH_API)
    if not _GH_API:
        return None
    r = requests.get(_GH_API, headers=_gh_headers(), params={"ref": GITHUB_BRANCH})
    if r.status_code == 404:
        logger.warning("GitHub: DB not found (404) at %s", _GH_API)
        return None
    r.raise_for_status()
    data = r.json()
    content = base64.b64decode(data["content"]) if isinstance(data.get("content"), str) else b""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(content)
    logger.info("GitHub: downloaded DB, sha=%s, bytes=%d", data.get("sha"), len(content))
    return data.get("sha")

def github_upload_db(src_path: Path, sha: str | None, message: str = "Update budget.db") -> str | None:
    """Upload DB to GitHub; returns new SHA. If 409 -> raise RuntimeError to be handled by caller."""
    if not _GH_API:
        return None
    logger.info("GitHub: uploading DB, prev sha=%s", sha)
    content_b64 = base64.b64encode(src_path.read_bytes()).decode()
    payload = {"message": message, "content": content_b64, "branch": GITHUB_BRANCH}
    if sha:
        payload["sha"] = sha
    r = requests.put(_GH_API, headers=_gh_headers(), data=json.dumps(payload))
    if r.status_code == 409:
        raise RuntimeError("Remote has changed (409). Pull latest and retry.")
    r.raise_for_status()
    logger.info("GitHub: uploaded DB, new sha=%s", r.json()["content"]["sha"])
    return r.json()["content"]["sha"]

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# --- Tooltip helper ---
class ToolTip:
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        lbl = ctk.CTkLabel(self.tip, text=self.text, text_color="#000000", fg_color="#ffffff")
        lbl.pack(ipadx=6, ipady=4)

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None

class BudgetApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Family Budget")
        self.geometry("750x720")
        self.resizable(True, True)

        self.sort_column = None
        self.sort_reverse = False
        self._notified = set()  # e.g., (category, '50'), ('Food','75')

        # Верхний frame (панель управления)
        self.top_frame = ctk.CTkFrame(self, height=130)
        self.top_frame.pack(fill='x', padx=20, pady=(20, 10))
        self.top_frame.grid_columnconfigure(4, weight=1)

        # Нижний контейнер с двумя колонками: слева таблица, справа сводка
        self.bottom_frame = ctk.CTkFrame(self)
        self.bottom_frame.pack(fill='both', expand=True, padx=20, pady=(0, 20))
        self.bottom_frame.grid_columnconfigure(0, weight=3)
        self.bottom_frame.grid_columnconfigure(1, weight=2)
        self.bottom_frame.grid_rowconfigure(0, weight=1)

        self.left_table_frame = ctk.CTkFrame(self.bottom_frame)
        self.left_table_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self.right_summary_frame = ctk.CTkFrame(self.bottom_frame)
        self.right_summary_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        self.create_top_panel()
        self.create_table()
        self.create_summary_panel()
        self.create_buttons()
        # Auto-push on close
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(120000, self._periodic_pull)  # каждые 2 минуты
        self._closed = False
        self.last_sync = None
        self.error_count = 0
        # Status bar at bottom
        self.status_var = tk.StringVar(value="Ready")
        self.status = ctk.CTkLabel(self, textvariable=self.status_var, anchor="w")
        self.status.pack(fill='x', side='bottom')
        atexit.register(self._atexit_push)


    def _atexit_push(self):
        # Fallback in case the window/process exits without WM_DELETE_WINDOW (e.g., Cmd+Q, IDE stop)
        if getattr(self, "_closed", False):
            return
        logger.info("Atexit: pushing DB...")
        try:
            self._push_db_best_effort("Atexit: update budget.db")
        except Exception:
            logger.warning("Atexit push failed", exc_info=True)

    def on_close(self):
        self._closed = True
        logger.info("Closing app: pushing DB...")
        try:
            self._push_db_best_effort("GUI close: update budget.db")
            logger.info("Closed app")
        finally:
            try:
                for h in logger.handlers:
                    try:
                        h.flush()
                    except Exception:
                        pass
            except Exception:
                pass
            self.destroy()

    def _periodic_pull(self):
        try:
            from bd import DB_FILE
            new_sha = github_download_db(Path(DB_FILE))
            if new_sha and new_sha != getattr(self, "_github_sha", None):
                self._github_sha = new_sha
                logger.info("Periodic pull: new sha=%s — refreshing UI", new_sha)
                self.refresh_table()
                self.update_remaining_indicator()
                self.update_summary_indicator()
                self._set_status(f"Pulled: {datetime.now().strftime('%H:%M:%S')} / Sha: {self._github_sha}")
        except Exception:
            self._inc_error("Periodic pull failed")
            pass
        finally:
            try:
                self.after(120000, self._periodic_pull)
            except Exception:
                pass

    def _backup_db(self, reason: str = "manual"):
        try:
            from bd import DB_FILE
            bdir = Path(DB_FILE).with_name("backups")
            bdir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            dst = bdir / f"budget_{ts}_{reason}.db"
            shutil.copy2(DB_FILE, dst)
            # rotate to keep last 7
            backs = sorted(bdir.glob("budget_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in backs[7:]:
                try: old.unlink()
                except Exception: pass
            logger.info("Backup created: %s", dst)
        except Exception:
            self._inc_error("Backup failed")

    def _push_db_best_effort(self, message: str):
        from bd import DB_FILE
        dbp = Path(DB_FILE)
        # create backup before any upload
        try: self._backup_db("push")
        except Exception: pass
        prev = getattr(self, "_github_sha", None)
        try:
            new_sha = github_upload_db(dbp, prev, message)
            if new_sha:
                self._github_sha = new_sha
                logger.info("GitHub push ok, sha=%s", new_sha)
                self._set_status(f"Pushed: {datetime.now().strftime('%H:%M:%S')} / Sha: {self._github_sha}")
                return
        except RuntimeError as e:
            if "409" in str(e):
                logger.warning("Push conflict (409). Pulling latest and retrying once...")
                try:
                    pulled = github_download_db(dbp)
                    if pulled:
                        self._github_sha = pulled
                        # merge remote into local to avoid data loss
                        try:
                            tmp_remote = dbp.with_name("_remote_tmp.db")
                            github_download_db(tmp_remote)
                            from bd import merge_db_from_file
                            merge_db_from_file(tmp_remote)
                            try: tmp_remote.unlink()
                            except Exception: pass
                        except Exception:
                            logger.warning("Soft-merge failed", exc_info=True)
                    new_sha = github_upload_db(dbp, self._github_sha, message + " (retry)")
                    if new_sha:
                        self._github_sha = new_sha
                        logger.info("Retry push ok, sha=%s", new_sha)
                        self._set_status(f"Pushed (retry): {datetime.now().strftime('%H:%M:%S')} / Sha: {self._github_sha}")
                        return
                except Exception:
                    self._inc_error("Push failed")
                    logger.error("Retry push failed", exc_info=True)
            else:
                self._inc_error("Push failed")
                logger.error("Push failed: %s", e)
        except Exception:
            self._inc_error("Push failed")
            logger.error("Push failed (unexpected)", exc_info=True)

    def _set_status(self, text: str):
        self.last_sync = text
        self.status_var.set(f"Last sync: {text}  |  Errors: {self.error_count}")

    def _inc_error(self, what: str = ""):
        self.error_count += 1
        self.status_var.set(f"Last sync: {(self.last_sync or '-') }  |  Errors: {self.error_count}")
        logger.warning("Status error: %s", what)

    def create_top_panel(self):
        # Выбор категории (динамически из БД; если пусто — дефолтный список)
        self.category_var = tk.StringVar(value="Food")
        self.category_menu = ctk.CTkOptionMenu(self.top_frame, variable=self.category_var, values=[], command=self.on_category_change)
        self.category_menu.grid(row=0, column=0, padx=10, pady=10)

        # Сначала создаём переменные месяца, чтобы ими мог пользоваться update_remaining_indicator
        curr_m = get_current_month()
        self.month_var = tk.StringVar(value=curr_m)
        self.compare_month_var = tk.StringVar(value=prev_month(curr_m))

        # Создаём remaining_var до первого вызова reload_categories / update_remaining_indicator
        self.remaining_var = tk.StringVar(value="Remaining: –")
        self.remaining_label = ctk.CTkLabel(self.top_frame, textvariable=self.remaining_var)
        self.remaining_label.grid(row=0, column=4, padx=10, pady=10, sticky="w")

        # Теперь можно загрузить категории (эта функция только обновляет values и не создаёт виджеты)
        self.reload_categories()

        # Поле суммы и кнопка добавления
        self.amount_entry = ctk.CTkEntry(self.top_frame, placeholder_text="amount")
        self.amount_entry.grid(row=0, column=1, padx=10, pady=10)
        def _validate_amount(action, value_if_allowed):
            if action == '0':
                return True
            try:
                if value_if_allowed.strip() in ('', '-', '.', ','):
                    return True
                float(value_if_allowed.replace(',', '.'))
                return True
            except ValueError:
                return False
        vcmd = (self.register(_validate_amount), '%d', '%P')
        self.amount_entry.configure(validate='key', validatecommand=vcmd)
        self.add_btn = ctk.CTkButton(self.top_frame, text="Add expenses", command=self.add_expense_btn)
        self.add_btn.grid(row=0, column=2, padx=10, pady=10)

        # Кнопка настроек справа
        try:
            self.top_frame.grid_columnconfigure(99, weight=1)
        except Exception:
            pass
        self.settings_btn = ctk.CTkButton(self.top_frame, text="⚙", height=44, width=54, font=("", 20, "bold"), command=self.open_settings)
        self.settings_btn.grid(row=0, column=100, padx=(10, 10), pady=8, sticky="e")

        # Компактные селекторы месяцев в одном блоке
        self.month_block = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self.month_block.grid(row=1, column=0, columnspan=4, padx=10, pady=(0, 6), sticky="w")
        ctk.CTkLabel(self.month_block, text="Month:").grid(row=0, column=0, padx=(0, 6), pady=0, sticky="w")
        self.month_menu = ctk.CTkOptionMenu(self.month_block, variable=self.month_var, values=[], command=self.on_month_change)
        self.month_menu.grid(row=0, column=1, padx=(0, 12), pady=0, sticky="w")
        ctk.CTkLabel(self.month_block, text="Compare:").grid(row=0, column=2, padx=(0, 6), pady=0, sticky="w")
        self.compare_month_menu = ctk.CTkOptionMenu(self.month_block, variable=self.compare_month_var, values=[], command=self.on_compare_month_change)
        self.compare_month_menu.grid(row=0, column=3, padx=(0, 0), pady=0, sticky="w")
        self.month_block.grid_columnconfigure(4, weight=1)
        self.update_month_menus()

        # Обновление индикатора остатка теперь безопасно (все переменные существуют)
        self.update_remaining_indicator()
    def reload_categories(self, prefer: str | None = None):
        """Обновить список категорий в верхнем меню из таблицы лимитов.
        Если в БД категорий нет, используем дефолтный список.
        """
        try:
            cats = [name for name, _ in (list_limits() or [])]
        except Exception:
            cats = []
        if not cats:
            cats = [
                "Food", "Travel", "Beer and Snacks", "Yummy", "Smoking", "Pharmacy",
                "Loan & Credit Cards", "Cloth", "Subscriptions", "Internet, Mobile",
                "Utilities", "Fun"
            ]
        # обновим values
        self.category_menu.configure(values=cats)
        # выбор значения
        if prefer and prefer in cats:
            self.category_var.set(prefer)
        else:
            cur = self.category_var.get()
            self.category_var.set(cur if cur in cats else cats[0])
        # Обновляем индикатор только если необходимые переменные уже созданы
        if hasattr(self, "month_var") and hasattr(self, "remaining_var"):
            self.update_remaining_indicator()


    def open_settings(self):
        try:
            SettingsDialog(self)
        except Exception as e:
            logger.error("Open settings failed: %s", e)
            messagebox.showerror("Error", f"Cannot open settings: {e}")

    def create_buttons(self):
        self.visual_frame = ctk.CTkFrame(self.top_frame)
        self.visual_frame.grid(row=2, column=0, columnspan=4, pady=(4, 4), sticky="w")
        self.pie_btn = ctk.CTkButton(self.visual_frame, text="🥧", width=36, height=32, command=self.show_pie_chart)
        self.pie_btn.grid(row=0, column=0, padx=(10, 6))
        ToolTip(self.pie_btn, "Pie chart")
        self.bar_btn = ctk.CTkButton(self.visual_frame, text="📊", width=36, height=32, command=self.show_bar_chart)
        self.bar_btn.grid(row=0, column=1, padx=(0, 10))
        ToolTip(self.bar_btn, "Bar chart")

    def create_table(self):
        columns = ('id', 'category', 'amount', 'date')
        self.table = ttk.Treeview(self.left_table_frame, columns=columns, show='headings', height=20)
        self.table.heading('id', text='id')
        self.table.heading('category', text='Category', command=lambda: self.sort_by('category'))
        self.table.heading('amount', text='Amount', command=lambda: self.sort_by('amount'))
        self.table.heading('date', text='Date', command=lambda: self.sort_by('date'))
        self.table.column('id', width=0, stretch=False)  # Скрываем id
        self.table.column('category', width=220)
        self.table.column('amount', width=120, anchor='e')
        self.table.column('date', width=140)
        # Toolbar above table
        toolbar = ctk.CTkFrame(self.left_table_frame)
        toolbar.pack(fill='x', padx=0, pady=(0, 4))
        self.search_var = tk.StringVar()
        search_entry = ctk.CTkEntry(toolbar, textvariable=self.search_var, placeholder_text="Search category...")
        search_entry.pack(side='left', padx=(0, 8))
        search_entry.bind('<KeyRelease>', lambda e: self.refresh_table())
        sync_btn = ctk.CTkButton(toolbar, text="Sync now", width=86, command=lambda: self._manual_sync())
        sync_btn.pack(side='left', padx=(0, 6))
        ToolTip(sync_btn, "Pull latest DB from GitHub")
        export_btn = ctk.CTkButton(toolbar, text="Export CSV", width=96, command=self._export_csv)
        export_btn.pack(side='left')
        ToolTip(export_btn, "Export current month to CSV")
        self.table.pack(fill='both', expand=True)
        self.table.bind('<Double-1>', self.on_double_click)
        self.table.bind('<<TreeviewSelect>>', self.on_table_select)
        # Контекстное меню для удаления записи
        self.table_menu = tk.Menu(self, tearoff=0)
        self.table_menu.add_command(label="Delete record", command=self.delete_selected_expense)
        # Правый клик (Windows/Linux) и Ctrl+клик (macOS трекпад)
        self.table.bind('<Button-3>', self.show_table_menu)
        self.table.bind('<Control-Button-1>', self.show_table_menu)
        self.table.tag_configure('oddrow', background='#b7b7b7')
        self.table.tag_configure('evenrow', background='#dddddd')
        self.refresh_table()

    def create_summary_panel(self):
        # Заголовок
        title = ctk.CTkLabel(self.right_summary_frame, text="Summary", font=("", 16, "bold"))
        title.grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 6))

        self.sum_category_var = tk.StringVar(value="Category: –")
        self.sum_budget_var = tk.StringVar(value="Budget: –")
        self.sum_spent_var = tk.StringVar(value="Spent: –")
        self.sum_remaining_var = tk.StringVar(value="Remaining: –")
        self.sum_rolled_var = tk.StringVar(value="Rolled over: –")

        ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_category_var).grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=2)
        ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_budget_var).grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=2)
        ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_spent_var).grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=2)
        self.sum_remaining_label = ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_remaining_var)
        self.sum_remaining_label.grid(row=4, column=0, columnspan=2, sticky="w", padx=10, pady=2)
        self.sum_remaining_default_color = self.sum_remaining_label.cget("text_color")
        ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_rolled_var).grid(row=5, column=0, columnspan=2, sticky="w", padx=10, pady=2)

        self.sum_vs_var = tk.StringVar(value="")
        self.sum_vs_label = ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_vs_var)
        self.sum_vs_label.grid(row=6, column=0, columnspan=2, sticky="w", padx=10, pady=(6, 2))

        self.usage_progress = ctk.CTkProgressBar(self.right_summary_frame)
        self.usage_progress.set(0)
        self.usage_progress.grid(row=7, column=0, columnspan=2, sticky="we", padx=10, pady=(8, 12))
        self.right_summary_frame.grid_columnconfigure(0, weight=1)
        self.right_summary_frame.grid_columnconfigure(1, weight=1)

        self.usage_default_color = self.usage_progress.cget("progress_color")

        self.update_summary_indicator()
        btn = ctk.CTkButton(self.right_summary_frame, text="Open Comparison", command=self.show_comparison_window)
        btn.grid(row=8, column=0, sticky="w", padx=10, pady=(4, 10))
        trends_btn = ctk.CTkButton(self.right_summary_frame, text="Trends", command=self.show_trends_window)
        trends_btn.grid(row=8, column=1, sticky="e", padx=10, pady=(4, 10))

    def update_summary_indicator(self):
        try:
            cat = self.category_var.get()
            report = get_month_report(self.month_var.get())
            data = report.get(cat)
            self.sum_category_var.set(f"Category: {cat}")
            if not data:
                # нет данных по лимиту/тратам
                self.sum_budget_var.set("Budget: $0.00")
                self.sum_spent_var.set("Spent: $0.00")
                self.sum_remaining_var.set("Remaining: $0.00")
                self.sum_rolled_var.set("Rolled over: $0.00")
                self.sum_remaining_label.configure(text_color=self.sum_remaining_default_color)
                self.usage_progress.set(0)
                self.sum_vs_var.set("")
                return
            budget = float(data.get("budget", 0.0))
            spent = float(data.get("spent", 0.0))
            remaining = float(data.get("remaining", 0.0))
            rolled = float(data.get("rolled_over", 0.0))

            self.sum_budget_var.set(f"Budget: ${budget:.2f}")
            self.sum_spent_var.set(f"Spent: ${spent:.2f}")
            self.sum_remaining_var.set(f"Remaining: ${remaining:.2f}")
            self.sum_rolled_var.set(f"Rolled over: ${rolled:.2f}")

            # Цвет при 90% использования
            usage = 0.0
            if budget > 0:
                usage = min(max(spent / budget, 0.0), 1.0)
            self.usage_progress.set(usage)
            if budget > 0 and usage >= 0.9:
                self.usage_progress.configure(progress_color="#ff4d4f")
                self.sum_remaining_label.configure(text_color="#ff4d4f")  # красный
            else:
                self.usage_progress.configure(progress_color=self.usage_default_color)
                self.sum_remaining_label.configure(text_color=self.sum_remaining_default_color)

            # сравнение с выбранным месяцем
            cmp_m = self.compare_month_var.get()
            try:
                cmp_report = get_month_report(cmp_m)
                cmp_spent = float(cmp_report.get(cat, {}).get("spent", 0.0))
                delta = spent - cmp_spent
                pct = (delta / cmp_spent * 100.0) if cmp_spent > 0 else 0.0
                self.sum_vs_var.set(f"vs {cmp_m}: Δ {delta:+.2f} ({pct:+.1f}%)")
            except Exception:
                self.sum_vs_var.set("")
        except Exception:
            # если что-то пошло не так — сбросить индикаторы
            self.sum_category_var.set("Category: –")
            self.sum_budget_var.set("Budget: –")
            self.sum_spent_var.set("Spent: –")
            self.sum_remaining_var.set("Remaining: –")
            self.sum_rolled_var.set("Rolled over: –")
            self.sum_remaining_label.configure(text_color=self.sum_remaining_default_color)
            self.usage_progress.set(0)
            self.sum_vs_var.set("")

    def on_table_select(self, event):
        sel = self.table.selection()
        if not sel:
            return
        row = self.table.item(sel[0])['values']
        if len(row) == 4:
            _id, category, _amount, _date = row
            # синхронизируем выбор категории в верхнем меню
            self.category_var.set(category)
            self.update_remaining_indicator()
            self.update_summary_indicator()

    def show_table_menu(self, event):
        row_id = self.table.identify_row(event.y)
        if row_id:
            self.table.selection_set(row_id)
            try:
                self.table_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.table_menu.grab_release()

    def delete_selected_expense(self):
        sel = self.table.selection()
        if not sel:
            return
        values = self.table.item(sel[0])['values']
        if len(values) != 4:
            return
        expense_id = values[0]
        if not messagebox.askyesno("Delete", f"Delete record #{expense_id}?"):
            return
        try:
            delete_expense(int(expense_id))
            logger.info("Deleted expense id=%s", expense_id)
            self.refresh_table()
            self.update_remaining_indicator()
            self.update_summary_indicator()
            self._push_db_best_effort("Delete expense")
        except Exception as e:
            logger.error("Delete expense failed: %s", e)
            messagebox.showerror("Error", f"Cannot delete: {e}")

    def refresh_table(self):
        for row in self.table.get_children():
            self.table.delete(row)
        expenses = get_expenses_for_month(self.month_var.get())
        # Search filter: supports category substrings, amount queries, date queries
        q_raw = (self.search_var.get().strip() if hasattr(self, 'search_var') else '')
        if q_raw:
            import re
            tokens = q_raw.split()
            def match(e):
                cat = str(e[1]).lower()
                amt = float(e[2])
                date = str(e[3])  # YYYY-MM-DD
                ok_all = True
                for t in tokens:
                    t_l = t.lower()
                    # amount range: 100..300
                    m = re.match(r'^(\d+(?:[\.,]\d+)?)\.\.(\d+(?:[\.,]\d+)?)$', t_l)
                    if m:
                        lo = float(m.group(1).replace(',', '.'))
                        hi = float(m.group(2).replace(',', '.'))
                        if not (lo <= amt <= hi):
                            ok_all = False; break
                        continue
                    # amount op: >100, <=200
                    m = re.match(r'^(>=|<=|>|<|=)?\s*(\d+(?:[\.,]\d+)?)$', t_l)
                    if m:
                        op = m.group(1) or '='
                        val = float(m.group(2).replace(',', '.'))
                        if not ((op == '>' and amt > val) or (op == '<' and amt < val) or (op == '>=' and amt >= val) or (op == '<=' and amt <= val) or (op in ('=', None) and amt == val)):
                            ok_all = False; break
                        continue
                    # date range: 2025-08..2025-09 or 2025-08-01..2025-08-15
                    m = re.match(r'^(\d{4}-\d{2}(?:-\d{2})?)\.\.(\d{4}-\d{2}(?:-\d{2})?)$', t_l)
                    if m:
                        lo, hi = m.group(1), m.group(2)
                        if not (lo <= date <= hi):
                            ok_all = False; break
                        continue
                    # date equals or prefix: 2025-08 or =2025-08-02
                    m = re.match(r'^=?\d{4}-\d{2}(?:-\d{2})?$', t_l)
                    if m:
                        val = t_l.lstrip('=')
                        if not date.startswith(val):
                            ok_all = False; break
                        continue
                    # default: category contains
                    if t_l not in cat:
                        ok_all = False; break
                return ok_all
            expenses = [e for e in expenses if match(e)]
        # Сортировка, если задана
        if self.sort_column:
            idx = {'id': 0, 'category': 1, 'amount': 2, 'date': 3}[self.sort_column]
            expenses.sort(key=lambda x: x[idx], reverse=self.sort_reverse)
        for expense in expenses:
            # expense = (id, category, amount, date)
            if len(expense) == 4:
                tag = 'evenrow' if len(self.table.get_children()) % 2 == 0 else 'oddrow'
                self.table.insert('', tk.END, values=expense, tags=(tag,))

    def _manual_sync(self):
        try:
            from bd import DB_FILE
            new_sha = github_download_db(Path(DB_FILE))
            if new_sha:
                self._github_sha = new_sha
                self.refresh_table()
                self.update_remaining_indicator()
                self.update_summary_indicator()
                self._set_status(f"Pulled (manual): {datetime.now().strftime('%H:%M:%S')} / Sha: {self._github_sha}")
        except Exception:
            self._inc_error("Manual sync failed")

    def _export_csv(self):
        try:
            path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV','*.csv')], initialfile=f"expenses_{self.month_var.get()}.csv")
            if not path:
                return
            import csv
            expenses = get_expenses_for_month(self.month_var.get())
            # apply current filter
            q = (self.search_var.get().strip().lower() if hasattr(self, 'search_var') else '')
            if q:
                expenses = [e for e in expenses if q in str(e[1]).lower()]
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['id','category','amount','date'])
                for row in expenses:
                    w.writerow(row)
            messagebox.showinfo("Export", f"Saved to {path}")
        except Exception as e:
            self._inc_error("Export failed")
            messagebox.showerror("Export", f"Failed: {e}")

    def sort_by(self, col):
        if self.sort_column == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = col
            self.sort_reverse = False
        self.refresh_table()

    def add_expense_btn(self):
        category = self.category_var.get()
        amount = self.amount_entry.get()
        try:
            amount = float(amount)
            logger.info("Add expense: %s %.2f", category, amount)
            exceeded, remaining = add_expense(category, amount)
            if exceeded:
                messagebox.showwarning(
                    "Budget limit",
                    f"Limit exceeded for {category}. Remaining: {remaining:.2f}"
                )
            self.amount_entry.delete(0, tk.END)
            self.refresh_table()
            self.update_remaining_indicator()
            self.update_summary_indicator()
            self.update_month_menus()
            # threshold notifications for selected category
            try:
                rep = get_month_report(self.month_var.get()).get(category, {})
                budget = float(rep.get('budget', 0.0))
                spent = float(rep.get('spent', 0.0))
                if budget > 0:
                    usage = spent / budget
                    for thr, label in [(0.5,'50'),(0.75,'75'),(0.9,'90')]:
                        key = (category, label, self.month_var.get())
                        if usage >= thr and key not in self._notified:
                            messagebox.showwarning('Budget threshold', f"{category}: reached {int(thr*100)}% of monthly limit")
                            self._notified.add(key)
            except Exception:
                pass
            self._push_db_best_effort("Add expense")
        except ValueError:
            logger.error("Add expense failed: not a number: %r", self.amount_entry.get())
            self.amount_entry.configure(border_color="#ff4d4f")
            self.after(1500, lambda: self.amount_entry.configure(border_color=None))
            return
        except Exception as e:
            logger.error("Set limit failed: %s", e)
            messagebox.showerror("Error", f"Cant save the limit: {e}")



    def on_category_change(self, value):
        # Обновляем индикатор при смене категории
        self.update_remaining_indicator()
        self.update_summary_indicator()
    def update_month_menus(self):
        months = list_months()
        curr_m = get_current_month()
        if curr_m not in months:
            months.insert(0, curr_m)
        self.month_menu.configure(values=months)
        self.compare_month_menu.configure(values=months)
        # если выбранный месяц выпал из списка — вернуть к текущему
        if self.month_var.get() not in months:
            self.month_var.set(curr_m)
        # если выбранный для сравнения отсутсвует — выбрать предыдущий от текущего
        if self.compare_month_var.get() not in months:
            pm = prev_month(self.month_var.get())
            self.compare_month_var.set(pm if pm in months else (months[1] if len(months) > 1 else self.month_var.get()))

    def on_month_change(self, value):
        self.refresh_table()
        self.update_remaining_indicator()
        self.update_summary_indicator()

    def on_compare_month_change(self, value):
        # просто обновим сводку (в ней появится строка сравнения)
        self.update_summary_indicator()

    def show_comparison_window(self):
        curr_m = self.month_var.get()
        cmp_m = self.compare_month_var.get()
        rep_curr = get_month_report(curr_m)
        rep_cmp = get_month_report(cmp_m)
        cats = sorted(set(rep_curr.keys()) | set(rep_cmp.keys()))

        win = ctk.CTkToplevel(self)
        win.title(f"Comparison: {curr_m} vs {cmp_m}")
        win.geometry("600x400")

        cols = ("category", "spent_curr", "spent_cmp", "delta", "pct")
        tv = ttk.Treeview(win, columns=cols, show='headings', height=15)
        for cid, text in zip(cols, ["Category", f"Spent {curr_m}", f"Spent {cmp_m}", "Δ", "%"]):
            tv.heading(cid, text=text)
        tv.column("category", width=160)
        tv.column("spent_curr", width=100)
        tv.column("spent_cmp", width=100)
        tv.column("delta", width=100)
        tv.column("pct", width=80)
        tv.pack(fill='both', expand=True, padx=10, pady=10)

        for cat in cats:
            sc = float(rep_curr.get(cat, {}).get("spent", 0.0))
            sp = float(rep_cmp.get(cat, {}).get("spent", 0.0))
            delta = sc - sp
            pct = (delta / sp * 100.0) if sp > 0 else 0.0
            tv.insert('', 'end', values=(cat, f"{sc:.2f}", f"{sp:.2f}", f"{delta:+.2f}", f"{pct:+.1f}%"))

    def update_remaining_indicator(self):
        try:
            category = self.category_var.get()
            remaining = get_remaining(category, self.month_var.get())
            self.remaining_var.set(f"Remaining: {remaining:.2f}")
        except Exception:
            self.remaining_var.set("Remaining: –")

    def on_double_click(self, event):
        item_id = self.table.selection()[0]
        row = self.table.item(item_id)['values']
        if len(row) == 4:
            expense_id, category, amount, date = row
            # Окно редактирования
            EditDialog(self, expense_id, category, amount, date, self.edit_callback)

    def edit_callback(self, expense_id, new_category, new_amount):
        try:
            logger.info("Edit expense id=%s -> (%s, %.2f)", expense_id, new_category, float(new_amount))
            update_expense(expense_id, new_category, float(new_amount))
            self.refresh_table()
            self.update_remaining_indicator()
            self.update_summary_indicator()
            self._push_db_best_effort("Edit expense")
        except Exception as e:
            logger.error("Edit expense failed: %s", e)
            messagebox.showerror("Error", f"Failed to update: {e}")

    def show_pie_chart(self):
        expenses = get_expenses_for_month(self.month_var.get())
        totals = {}
        for _, category, amount, _ in expenses:
            totals[category] = totals.get(category, 0) + float(amount)
        try:
            ap = get_apartment_payment()
            if ap is not None and float(ap) > 0:
                totals["Apartment payment"] = totals.get("Apartment payment", 0) + float(ap)
        except Exception:
            pass
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        if not totals:
            ax.text(0.5, 0.5, 'No data', ha='center', va='center')
        else:
            ax.pie(list(totals.values()), labels=list(totals.keys()), autopct='%1.1f%%', textprops={'color':'black'})
        ax.set_title("Expenses by Category")
        fig.tight_layout()
        plt.show()

    def show_bar_chart(self):
        expenses = get_expenses_for_month(self.month_var.get())
        totals = {}
        for _, category, amount, _ in expenses:
            totals[category] = totals.get(category, 0) + float(amount)
        try:
            ap = get_apartment_payment()
            if ap is not None and float(ap) > 0:
                totals["Apartment payment"] = totals.get("Apartment payment", 0) + float(ap)
        except Exception:
            pass
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        if not totals:
            ax.text(0.5, 0.5, 'No data', ha='center', va='center')
        else:
            cats = list(totals.keys()); vals = list(totals.values())
            x = range(len(cats))
            ax.bar(x, vals)
            ax.set_xticks(list(x))
            ax.set_xticklabels(cats, rotation=30, ha='right', color='black')
            ax.tick_params(axis='y', colors='black')
        ax.set_ylabel("Amount")
        ax.set_title("Expenses by Category")
        fig.tight_layout()
        plt.show()

    def show_trends_window(self):
        months = list_months()
        totals = []
        for m in months:
            rep = get_month_report(m)
            total_spent = sum(float(d.get('spent',0.0)) for d in rep.values())
            totals.append((m, total_spent))
        win = ctk.CTkToplevel(self)
        win.title("Trends")
        win.geometry("720x420")
        from matplotlib.figure import Figure
        fig = Figure(figsize=(6.8, 3.8), dpi=100)
        ax = fig.add_subplot(111)
        if totals:
            xs = [t[0] for t in totals]
            ys = [t[1] for t in totals]
            ax.plot(xs, ys, marker='o')
            ax.set_xticklabels(xs, rotation=30, ha='right', color='black')
            ax.set_ylabel('Total spent')
            ax.set_title('Monthly total')
        else:
            ax.text(0.5, 0.5, 'No data', ha='center', va='center')
        cv = FigureCanvasTkAgg(fig, master=win)
        cv.get_tk_widget().pack(fill='both', expand=True, padx=10, pady=10)
        cv.draw()

class EditDialog(ctk.CTkToplevel):
    def __init__(self, parent, expense_id, category, amount, date, on_save):
        super().__init__(parent)
        self.title("Edit Expense")
        self.geometry("200x260")
        self.resizable(False, False)
        self.on_save = on_save
        self.expense_id = expense_id

        ctk.CTkLabel(self, text=f"Date: {date}").pack(pady=5)
        ctk.CTkLabel(self, text="Category:").pack()
        self.category_var = tk.StringVar(value=category)
        # Dynamic categories from DB limits, with sensible fallback
        try:
            cats = [name for name, _ in (list_limits() or [])]
        except Exception:
            cats = []
        if not cats:
            cats = [
                "Food", "Travel", "Beer and Snacks", "Yummy", "Smoking", "Pharmacy",
                "Loan & Credit Cards", "Cloth", "Subscriptions", "Internet, Mobile",
                "Utilities", "Fun"
            ]
        # Ensure current category is present and preselected
        if category not in cats:
            cats = [category] + [c for c in cats if c != category]
        self.cat_menu = ctk.CTkOptionMenu(self, variable=self.category_var, values=cats)
        self.cat_menu.pack()

        ctk.CTkLabel(self, text="Amount:").pack()
        self.amount_entry = ctk.CTkEntry(self)
        self.amount_entry.insert(0, amount)
        self.amount_entry.pack()

        ctk.CTkButton(self, text="Save", command=self.save).pack(pady=10)
        ctk.CTkButton(self, text="Cancel", command=self.destroy).pack()

    def save(self):
        self.on_save(self.expense_id, self.category_var.get(), self.amount_entry.get())
        self.destroy()


# --- Settings dialog ---
class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent: "BudgetApp"):
        super().__init__(parent)
        self.parent = parent
        self.title("Settings")
        try:
            self.geometry("460x450")
        except Exception:
            pass
        self.resizable(True, True)

        # --- Apartment payment section ---
        apart_frame = ctk.CTkFrame(self)
        apart_frame.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkLabel(apart_frame, text="Apartment payment (per month)").grid(row=0, column=0, padx=8, pady=(8, 4), sticky="w")
        self.apart_entry = ctk.CTkEntry(apart_frame, placeholder_text="e.g. 45000")
        self.apart_entry.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="we")
        apart_frame.grid_columnconfigure(0, weight=1)
        # prefill from DB
        try:
            ap = get_apartment_payment()
            if ap is not None:
                self.apart_entry.insert(0, f"{float(ap):.2f}")
        except Exception:
            pass
        save_ap_btn = ctk.CTkButton(apart_frame, text="Save apartment payment", command=self._save_apartment)
        save_ap_btn.grid(row=1, column=1, padx=8, pady=(0, 8))

        # --- Category limits section ---
        limits_frame = ctk.CTkFrame(self)
        limits_frame.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(limits_frame, text="Category limits").grid(row=0, column=0, columnspan=3, padx=8, pady=(8, 6), sticky="w")

        # existing categories dropdown
        try:
            self.cat_values = [name for name, _ in (list_limits() or [])]
        except Exception:
            self.cat_values = []
        self.cat_var = tk.StringVar(value=self.cat_values[0] if self.cat_values else "")
        self.cat_combo = ctk.CTkOptionMenu(limits_frame, variable=self.cat_var, values=self.cat_values)
        self.cat_combo.grid(row=1, column=0, padx=8, pady=2, sticky="we")

        # limit value entry for selected category
        self.limit_entry = ctk.CTkEntry(limits_frame, placeholder_text="Default monthly limit")
        self.limit_entry.grid(row=1, column=1, padx=8, pady=2, sticky="we")

        # Set limit button
        ctk.CTkButton(limits_frame, text="Set limit", command=self._save_limit_default).grid(row=1, column=2, padx=8, pady=2)

        limits_frame.grid_columnconfigure(0, weight=1)
        limits_frame.grid_columnconfigure(1, weight=1)

        # Separator between sections
        sep = ctk.CTkFrame(self, height=2)
        sep.pack(fill="x", padx=14, pady=(10, 0))

        # --- Add Category section ---
        addcat_frame = ctk.CTkFrame(self)
        addcat_frame.pack(fill="x", padx=14, pady=(10, 14))
        ctk.CTkLabel(addcat_frame, text="Add Category").grid(row=0, column=0, columnspan=2, padx=8, pady=(8, 6), sticky="w")

        self.new_cat_entry = ctk.CTkEntry(addcat_frame, placeholder_text="Category name")
        self.new_cat_entry.grid(row=1, column=0, padx=8, pady=2, sticky="we")
        self.new_cat_limit_entry = ctk.CTkEntry(addcat_frame, placeholder_text="Default limit (optional)")
        self.new_cat_limit_entry.grid(row=1, column=1, padx=8, pady=2, sticky="we")
        ctk.CTkButton(addcat_frame, text="Add Category", command=self._add_category).grid(row=1, column=2, padx=8, pady=2)

        addcat_frame.grid_columnconfigure(0, weight=1)
        addcat_frame.grid_columnconfigure(1, weight=1)
        # Separator between sections
        sep2 = ctk.CTkFrame(self, height=2)
        sep2.pack(fill="x", padx=14, pady=(0, 0))

        # --- Delete Category section ---
        delcat_frame = ctk.CTkFrame(self)
        delcat_frame.pack(fill="x", padx=14, pady=(10, 14))
        ctk.CTkLabel(delcat_frame, text="Delete Category").grid(row=0, column=0, columnspan=2, padx=8, pady=(8, 6),
                                                                sticky="w")

        # dropdown of existing categories
        try:
            self.del_cat_values = [name for name, _ in (list_limits() or [])]
        except Exception:
            self.del_cat_values = []
        self.del_cat_var = tk.StringVar(value=self.del_cat_values[0] if self.del_cat_values else "")
        self.del_cat_combo = ctk.CTkOptionMenu(delcat_frame, variable=self.del_cat_var, values=self.del_cat_values)
        self.del_cat_combo.grid(row=1, column=0, padx=8, pady=2, sticky="we")

        ctk.CTkButton(
            delcat_frame, text="Delete Category",
            fg_color="#b72b2b", hover_color="#8f1f1f",
            command=self._delete_category
        ).grid(row=1, column=1, padx=8, pady=2)

        delcat_frame.grid_columnconfigure(0, weight=1)

        # --- Logging section ---
        log_frame = ctk.CTkFrame(self)
        log_frame.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(log_frame, text="Logging").grid(row=0, column=0, padx=8, pady=(8, 6), sticky="w")
        levels = ["DEBUG","INFO","WARNING","ERROR"]
        cur = logging.getLevelName(logger.level)
        self.log_var = tk.StringVar(value=cur if cur in levels else "INFO")
        self.log_menu = ctk.CTkOptionMenu(log_frame, variable=self.log_var, values=levels)
        self.log_menu.grid(row=0, column=1, padx=8, pady=(8, 6), sticky="w")
        ctk.CTkButton(log_frame, text="Apply level", command=self._apply_log_level).grid(row=0, column=2, padx=8, pady=(8, 6))
        ctk.CTkButton(log_frame, text="Open log file", command=self._open_log_file).grid(row=0, column=3, padx=8, pady=(8, 6))
        log_frame.grid_columnconfigure(1, weight=1)

    # --- actions ---
    def _delete_category(self):
        name = (self.del_cat_var.get() or "").strip()
        if not name:
            messagebox.showerror("Error", "Select category to delete")
            return
        warn = (
            f"You are about to delete category '{name}'.\n\n"
            "This will also DELETE ALL expenses recorded in this category, "
            "and remove its budgets and limits. ВСË УДАЛИТСЯ НАХРЕН.\n\n"
            "Are you sure?"
        )
        if not messagebox.askokcancel("Confirm deletion", warn):
            return
        try:
            delete_category(name)

            # Обновляем выпадашки в диалоге
            try:
                self.cat_values = [n for n, _ in (list_limits() or [])]
            except Exception:
                self.cat_values = []
            self.cat_combo.configure(values=self.cat_values)
            self.del_cat_values = list(self.cat_values)
            self.del_cat_combo.configure(values=self.del_cat_values)
            self.cat_var.set(self.cat_values[0] if self.cat_values else "")
            self.del_cat_var.set(self.del_cat_values[0] if self.del_cat_values else "")

            # Обновляем главное окно
            try:
                self.parent.reload_categories()
                self.parent.refresh_table()
                self.parent.update_remaining_indicator()
                self.parent.update_summary_indicator()
            except Exception:
                pass

            # Пушим изменения
            self.parent._push_db_best_effort("Delete category and expenses")

            messagebox.showinfo("Deleted", f"Category '{name}' and all its expenses were deleted")
        except Exception as e:
            messagebox.showerror("Error", f"Cannot delete category: {e}")
    def _add_category(self):
        name = self.new_cat_entry.get().strip()
        if not name:
            messagebox.showerror("Error", "Enter new category name")
            return
        raw = self.new_cat_limit_entry.get().strip()
        try:
            amount = float(raw) if raw else 0.0
        except ValueError:
            messagebox.showerror("Error", "Limit must be a number")
            return

        # duplicate check (case-insensitive): treat 'Food' and 'food' as the same
        try:
            existing_lc = [n.lower() for n, _ in (list_limits() or [])]
        except Exception:
            existing_lc = []
        if name.lower() in existing_lc:
            messagebox.showerror("Error", f"Category '{name}' already exists")
            return

        try:
            set_limit(name, amount)
            # refresh parent category dropdown & select new category
            try:
                self.parent.reload_categories(prefer=name)
            except Exception:
                pass
            # refresh dropdown values
            try:
                self.cat_values = [n for n, _ in (list_limits() or [])]
            except Exception:
                self.cat_values = []
            self.cat_combo.configure(values=self.cat_values)
            self.cat_var.set(name)
            # also refresh Delete Category dropdown dynamically
            try:
                self.del_cat_values = list(self.cat_values)
            except Exception:
                self.del_cat_values = []
            if hasattr(self, 'del_cat_combo'):
                self.del_cat_combo.configure(values=self.del_cat_values)
            if hasattr(self, 'del_cat_var'):
                self.del_cat_var.set(name)
            # clear inputs
            self.new_cat_entry.delete(0, tk.END)
            self.new_cat_limit_entry.delete(0, tk.END)
            # push to GitHub and notify
            self.parent._push_db_best_effort("Add category")
            messagebox.showinfo("Saved", f"Category '{name}' added with default limit {amount:.2f}")
            # refresh parent UI if needed
            self._refresh_parent_after_limits()
        except Exception as e:
            messagebox.showerror("Error", f"Cannot add category: {e}")



    def _save_apartment(self):
        raw = self.apart_entry.get().strip()
        if not raw:
            messagebox.showerror("Error", "Enter apartment payment amount")
            return
        try:
            amount = float(raw)
            set_apartment_payment(amount)
            self.parent._push_db_best_effort("Update apartment payment")
            messagebox.showinfo("Saved", f"Apartment payment saved: {amount:.2f}")
        except Exception as e:
            messagebox.showerror("Error", f"Cannot save: {e}")

    def _save_limit_default(self):
        name = self.cat_var.get().strip()
        if not name:
            messagebox.showerror("Error", "Select category")
            return
        raw = self.limit_entry.get().strip()
        if not raw:
            messagebox.showerror("Error", "Enter limit amount")
            return
        try:
            amount = float(raw)
            set_limit(name, amount)
            try:
                self.parent.reload_categories()
            except Exception:
                pass
            # keep Delete Category dropdown in sync as well
            try:
                self.cat_values = [n for n, _ in (list_limits() or [])]
                self.del_cat_values = list(self.cat_values)
                if hasattr(self, 'del_cat_combo'):
                    self.del_cat_combo.configure(values=self.del_cat_values)
                if hasattr(self, 'del_cat_var') and self.cat_values:
                    self.del_cat_var.set(self.cat_values[0])
            except Exception:
                pass
            # refresh parent UI combos if needed
            self._refresh_parent_after_limits()
            self.parent._push_db_best_effort("Update default limit")
            messagebox.showinfo("Saved", f"Default limit for '{name}' saved: {amount:.2f}")
        except Exception as e:
            messagebox.showerror("Error", f"Cannot save limit: {e}")



    def _refresh_parent_after_limits(self):
        # обновить выпадашки категорий/индикаторы у родителя, если он их использует
        try:
            if hasattr(self.parent, "reload_categories"):
                self.parent.reload_categories()
        except Exception:
            pass
        try:
            self.parent.update_remaining_indicator()
            self.parent.update_summary_indicator()
        except Exception:
            pass


if __name__ == "__main__":
    # Pull latest DB from GitHub before opening UI (best-effort)
    from bd import DB_FILE
    db_path = Path(DB_FILE)
    logger.info("Startup: downloading DB from GitHub to %s", db_path)
    try:
        _initial_sha = github_download_db(db_path)
    except Exception:
        _initial_sha = None
        logger.error("Startup: GitHub download failed", exc_info=True)
    app = BudgetApp()
    app._github_sha = _initial_sha
    app._set_status(f"Pulled: {datetime.now().strftime('%H:%M:%S')} / Sha: {app._github_sha}")
    logger.info("Startup: DB sha=%s", _initial_sha)
    app.mainloop()
    def _apply_log_level(self):
        lvl = self.log_var.get()
        try:
            level = getattr(logging, lvl, logging.INFO)
            logger.setLevel(level)
            for h in logger.handlers:
                h.setLevel(level)
            messagebox.showinfo("Logging", f"Level set to {lvl}")
        except Exception as e:
            messagebox.showerror("Logging", f"Failed: {e}")

    def _open_log_file(self):
        try:
            from bd import DB_FILE
            log_file = Path(DB_FILE).with_name("app.log")
            if sys.platform.startswith('darwin'):
                os.system(f'open "{log_file}"')
            elif os.name == 'nt':
                os.startfile(str(log_file))
            else:
                os.system(f'xdg-open "{log_file}"')
        except Exception as e:
            messagebox.showerror("Open log", f"Failed: {e}")