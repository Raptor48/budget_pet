import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from bd import get_expenses, get_expenses_for_month, add_expense, update_expense, set_limit_and_apply, get_remaining, get_month_report, set_apartment_payment, get_apartment_payment, list_months, get_current_month, prev_month
import matplotlib.pyplot as plt
import subprocess
from pathlib import Path
from datetime import datetime
from bd import DB_FILE, repo_root, db_relpath_within_repo

# --- Git automation helpers ---
REPO_ROOT = repo_root()

def _git(*args):
    """Run a git command in repo root and return (returncode, stdout, stderr)."""
    proc = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

def git_pull_startup():
    """Pull latest changes before opening the app UI (best-effort)."""
    _git("fetch")
    rc, out, err = _git("pull", "--rebase")
    if rc != 0:
        _git("pull")  # fallback

def git_add_commit_push(message: str | None = None):
    """Stage DB and push changes (best-effort, no hard failures)."""
    try:
        db_rel = Path(DB_FILE)
        if db_rel.is_absolute():
            try:
                db_rel = db_rel.relative_to(REPO_ROOT)
            except ValueError:
                # DB is outside repo; nothing to do
                return
        _git("add", str(db_rel))
        if message is None:
            message = f"Auto-update DB {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        _git("commit", "-m", message)  # может быть no-op — окей
        _git("push")
    except Exception:
        # best-effort: не мешаем работе приложения
        pass

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

class BudgetApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Family Budget")
        self.geometry("1000x700")
        self.resizable(False, False)

        self.sort_column = None
        self.sort_reverse = False

        # Верхний frame (панель управления)
        self.top_frame = ctk.CTkFrame(self, height=180)
        self.top_frame.pack(fill='x', padx=20, pady=(20, 10))

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

    def on_close(self):
        # Commit and push DB changes on exit (best-effort)
        git_add_commit_push()
        self.destroy()

    def create_top_panel(self):
        self.category_var = tk.StringVar(value="Food")
        categories = ["Food", "Travel", "Beer and Snacks", "Yummy", "Smoking","Pharmacy", "Loan & Credit Cards","Cloth",
                      "Subscriptions", "Internet, Mobile","Utilities","Fun" ]

        self.category_menu = ctk.CTkOptionMenu(self.top_frame, variable=self.category_var, values=categories, command=self.on_category_change)
        self.category_menu.grid(row=0, column=0, padx=10, pady=10)

        self.amount_entry = ctk.CTkEntry(self.top_frame, placeholder_text="amount")
        self.amount_entry.grid(row=0, column=1, padx=10, pady=10)

        self.add_btn = ctk.CTkButton(self.top_frame, text="Add expanses", command=self.add_expense_btn)
        self.add_btn.grid(row=0, column=2, padx=10, pady=10)

        # Выбор месяца и месяца для сравнения
        months = list_months()
        curr_m = get_current_month()
        if curr_m not in months:
            months.insert(0, curr_m)
        self.month_var = tk.StringVar(value=curr_m)
        self.compare_month_var = tk.StringVar(value=prev_month(curr_m))

        ctk.CTkLabel(self.top_frame, text="Month:").grid(row=1, column=0, padx=10, pady=(0, 10), sticky="w")
        self.month_menu = ctk.CTkOptionMenu(self.top_frame, variable=self.month_var, values=months, command=self.on_month_change)
        self.month_menu.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="w")

        ctk.CTkLabel(self.top_frame, text="Compare:").grid(row=1, column=2, padx=10, pady=(0, 10), sticky="w")
        self.compare_month_menu = ctk.CTkOptionMenu(self.top_frame, variable=self.compare_month_var, values=months, command=self.on_compare_month_change)
        self.compare_month_menu.grid(row=1, column=3, padx=10, pady=(0, 10), sticky="w")

        # Поле и кнопка для установки лимита на месяц
        self.limit_entry = ctk.CTkEntry(self.top_frame, placeholder_text="Limit for month")
        self.limit_entry.grid(row=0, column=3, padx=10, pady=10)
        self.save_limit_btn = ctk.CTkButton(self.top_frame, text="Save limit", command=self.save_limit_btn_click)
        self.save_limit_btn.grid(row=0, column=4, padx=10, pady=10)
        # Поле и кнопка для текущего платежа за квартиру
        self.apart_entry = ctk.CTkEntry(self.top_frame, placeholder_text="Current apart. payment")
        self.apart_entry.grid(row=2, column=3, padx=10, pady=(0, 10))
        # Префилл суммы из БД, если уже сохранена
        try:
            _ap = get_apartment_payment()
            if _ap is not None:
                self.apart_entry.insert(0, f"{_ap:.2f}")
        except Exception:
            pass
        self.save_apart_btn = ctk.CTkButton(self.top_frame, text="Save", command=self.save_apart_btn_click)
        self.save_apart_btn.grid(row=2, column=4, padx=10, pady=(0, 10))

        # Индикатор остатка по выбранной категории
        self.remaining_var = tk.StringVar(value="Remaining: –")
        self.remaining_label = ctk.CTkLabel(self.top_frame, textvariable=self.remaining_var)
        self.remaining_label.grid(row=0, column=5, padx=10, pady=10)

        self.update_remaining_indicator()

    def create_buttons(self):
        # Кнопки для визуализации
        self.visual_frame = ctk.CTkFrame(self.top_frame)
        self.visual_frame.grid(row=3, column=0, columnspan=3, pady=10)
        pie_btn = ctk.CTkButton(self.visual_frame, text="Circle Chart", command=self.show_pie_chart)
        pie_btn.grid(row=0, column=0, padx=10)
        bar_btn = ctk.CTkButton(self.visual_frame, text="Line Chart", command=self.show_bar_chart)
        bar_btn.grid(row=0, column=1, padx=10)

    def create_table(self):
        columns = ('id', 'category', 'amount', 'date')
        self.table = ttk.Treeview(self.left_table_frame, columns=columns, show='headings', height=20)
        self.table.heading('id', text='id')
        self.table.heading('category', text='category', command=lambda: self.sort_by('category'))
        self.table.heading('amount', text='amount', command=lambda: self.sort_by('amount'))
        self.table.heading('date', text='date', command=lambda: self.sort_by('date'))
        self.table.column('id', width=0, stretch=False)  # Скрываем id
        self.table.pack(fill='both', expand=True)
        self.table.bind('<Double-1>', self.on_double_click)
        self.table.bind('<<TreeviewSelect>>', self.on_table_select)
        self.table.tag_configure('oddrow', background='#b7b7b7')
        self.table.tag_configure('evenrow', background='#dddddd')
        self.refresh_table()

    def create_summary_panel(self):
        # Заголовок
        title = ctk.CTkLabel(self.right_summary_frame, text="Summary", font=("", 16, "bold"))
        title.pack(anchor="w", pady=(10, 10), padx=10)

        # Строки со сводными данными
        self.sum_category_var = tk.StringVar(value="Category: –")
        self.sum_budget_var = tk.StringVar(value="Budget: –")
        self.sum_spent_var = tk.StringVar(value="Spent: –")
        self.sum_remaining_var = tk.StringVar(value="Remaining: –")
        self.sum_rolled_var = tk.StringVar(value="Rolled over: –")

        ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_category_var).pack(anchor="w", padx=10, pady=2)
        ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_budget_var).pack(anchor="w", padx=10, pady=2)
        ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_spent_var).pack(anchor="w", padx=10, pady=2)
        self.sum_remaining_label = ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_remaining_var)
        self.sum_remaining_label.pack(anchor="w", padx=10, pady=2)
        self.sum_remaining_default_color = self.sum_remaining_label.cget("text_color")
        ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_rolled_var).pack(anchor="w", padx=10, pady=2)

        # сравнение с месяцем для сравнения
        self.sum_vs_var = tk.StringVar(value="")
        self.sum_vs_label = ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_vs_var)
        self.sum_vs_label.pack(anchor="w", padx=10, pady=(6, 2))

        # прогресс-бар по категории (процент использования бюджета)
        self.usage_progress = ctk.CTkProgressBar(self.right_summary_frame)
        self.usage_progress.set(0)
        self.usage_progress.pack(fill='x', padx=10, pady=(8, 12))

        self.usage_default_color = self.usage_progress.cget("progress_color")

        # первичное обновление
        self.update_summary_indicator()
        ctk.CTkButton(self.right_summary_frame, text="Open Comparison", command=self.show_comparison_window).pack(anchor="w", padx=10, pady=(8, 10))

    def update_summary_indicator(self):
        try:
            cat = self.category_var.get()
            report = get_month_report(self.month_var.get())
            data = report.get(cat)
            self.sum_category_var.set(f"Category: {cat}")
            if not data:
                # нет данных по лимиту/тратам
                self.sum_budget_var.set("Budget: 0.00")
                self.sum_spent_var.set("Spent: 0.00")
                self.sum_remaining_var.set("Remaining: 0.00")
                self.sum_rolled_var.set("Rolled over: 0.00")
                self.sum_remaining_label.configure(text_color=self.sum_remaining_default_color)
                self.usage_progress.set(0)
                self.sum_vs_var.set("")
                return
            budget = float(data.get("budget", 0.0))
            spent = float(data.get("spent", 0.0))
            remaining = float(data.get("remaining", 0.0))
            rolled = float(data.get("rolled_over", 0.0))

            self.sum_budget_var.set(f"Budget: {budget:.2f}")
            self.sum_spent_var.set(f"Spent: {spent:.2f}")
            self.sum_remaining_var.set(f"Remaining: {remaining:.2f}")
            self.sum_rolled_var.set(f"Rolled over: {rolled:.2f}")

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

    def refresh_table(self):
        for row in self.table.get_children():
            self.table.delete(row)
        expenses = get_expenses_for_month(self.month_var.get())
        # Сортировка, если задана
        if self.sort_column:
            idx = {'id': 0, 'category': 1, 'amount': 2, 'date': 3}[self.sort_column]
            expenses.sort(key=lambda x: x[idx], reverse=self.sort_reverse)
        for expense in expenses:
            # expense = (id, category, amount, date)
            if len(expense) == 4:
                tag = 'evenrow' if len(self.table.get_children()) % 2 == 0 else 'oddrow'
                self.table.insert('', tk.END, values=expense, tags=(tag,))

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
            git_add_commit_push("Add expense")
        except ValueError:
            messagebox.showerror("error", "numbers only")
            self.amount_entry.delete(0, tk.END)

    def save_limit_btn_click(self):
        category = self.category_var.get()
        raw = self.limit_entry.get().strip()
        try:
            amount = float(raw)
        except ValueError:
            messagebox.showerror("error", "numbers only")
            self.limit_entry.delete(0, tk.END)
            return
        try:
            set_limit_and_apply(category, amount)
            messagebox.showinfo("OK", f"Limit for '{category}' set: {amount:.2f}")
            self.refresh_table()
            self.update_remaining_indicator()
            self.update_summary_indicator()
            self.update_month_menus()
            git_add_commit_push("Update limit")
        except Exception as e:
            messagebox.showerror("Error", f"Cant save the limit: {e}")

    def save_apart_btn_click(self):
        raw = self.apart_entry.get().strip()
        try:
            amount = float(raw)
        except ValueError:
            messagebox.showerror("error", "numbers only")
            self.apart_entry.delete(0, tk.END)
            return
        try:
            set_apartment_payment(amount)
            messagebox.showinfo("ok", f"Apartment payment saved: {amount:.2f}")
            self.apart_entry.delete(0, tk.END)
            git_add_commit_push("Update apartment payment")
        except Exception as e:
            messagebox.showerror("error", f"cannot save: {e}")

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
            update_expense(expense_id, new_category, float(new_amount))
            self.refresh_table()
            self.update_remaining_indicator()
            self.update_summary_indicator()
            git_add_commit_push("Edit expense")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update: {e}")

    # ----- Простые заглушки визуализации -----
    def show_pie_chart(self):
        expenses = get_expenses_for_month(self.month_var.get())
        category_totals = {}
        for _, category, amount, _ in expenses:
            category_totals[category] = category_totals.get(category, 0) + float(amount)
        # Добавляем платеж за квартиру как отдельную категорию, если задан
        try:
            ap = get_apartment_payment()
            if ap is not None and float(ap) > 0:
                category_totals["Apartment payment"] = category_totals.get("Apartment payment", 0) + float(ap)
        except Exception:
            pass
        plt.figure(figsize=(6,6))
        plt.pie(category_totals.values(), labels=category_totals.keys(), autopct='%1.1f%%')
        plt.title("Expenses by Category (incl. Apartment)")
        plt.show()

    def show_bar_chart(self):
        expenses = get_expenses_for_month(self.month_var.get())
        category_totals = {}
        for _, category, amount, _ in expenses:
            category_totals[category] = category_totals.get(category, 0) + float(amount)
        # Добавляем платеж за квартиру как отдельную категорию, если задан
        try:
            ap = get_apartment_payment()
            if ap is not None and float(ap) > 0:
                category_totals["Apartment payment"] = category_totals.get("Apartment payment", 0) + float(ap)
        except Exception:
            pass
        plt.figure(figsize=(10,6))
        plt.bar(category_totals.keys(), category_totals.values())
        plt.title("Expenses by Category (incl. Apartment)")
        plt.ylabel("Amount")
        plt.xticks(rotation=30, ha='right')
        plt.tight_layout()
        plt.show()

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
        categories = ["Food", "Travel", "Beer and Snacks", "Yummy", "Smoking","Pharmacy", "Loan & Credit Cards","Cloth", "Subscriptions", "Internet, Mobile","Utilities","Fun" ]
        ctk.CTkOptionMenu(self, variable=self.category_var, values=categories).pack()

        ctk.CTkLabel(self, text="Amount:").pack()
        self.amount_entry = ctk.CTkEntry(self)
        self.amount_entry.insert(0, amount)
        self.amount_entry.pack()

        ctk.CTkButton(self, text="Save", command=self.save).pack(pady=10)
        ctk.CTkButton(self, text="Cancel", command=self.destroy).pack()

    def save(self):
        self.on_save(self.expense_id, self.category_var.get(), self.amount_entry.get())
        self.destroy()

if __name__ == "__main__":
    # Pull latest DB on start (best-effort)
    git_pull_startup()
    app = BudgetApp()
    app.mainloop()