import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import sys
from pathlib import Path
from bd import (
    get_expenses_for_month, add_expense, update_expense, delete_expense,
    set_limit_and_apply, set_limit, list_limits, delete_category,
    set_apartment_payment, get_apartment_payment, get_current_month
)
from services.logging_config import get_logger

logger = get_logger("budget-dialogs")

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

        ctk.CTkButton(self, text="Save", command=self.save).pack(pady=(10, 4))
        ctk.CTkButton(self, text="Cancel", command=self.destroy).pack(pady=(0, 6))

        ctk.CTkButton(
            self,
            text="Delete",
            fg_color="#b72b2b",
            hover_color="#8f1f1f",
            command=self.delete_record
        ).pack()

    def save(self):
        self.on_save(self.expense_id, self.category_var.get(), self.amount_entry.get())
        self.destroy()

    def delete_record(self):
        if not messagebox.askyesno("Delete", f"Delete record #{self.expense_id}?"):
            return
        try:
            delete_expense(int(self.expense_id))
            logger.info("Deleted expense id=%s (from EditDialog)", self.expense_id)
            # Update parent
            try:
                self.master.refresh_table()
                self.master.update_remaining_indicator()
                self.master.update_summary_indicator()
                self.master._push_db_best_effort("Delete expense (from edit)")
            except Exception:
                pass
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Cannot delete: {e}")


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Settings")
        try:
            self.geometry("460x450")
        except Exception:
            pass
        self.resizable(True, True)

        # Apartment payment section
        apart_frame = ctk.CTkFrame(self)
        apart_frame.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkLabel(apart_frame, text="Apartment payment (per month)").grid(row=0, column=0, padx=8, pady=(8, 4), sticky="w")
        self.apart_entry = ctk.CTkEntry(apart_frame, placeholder_text="e.g. 45000")
        self.apart_entry.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="we")
        apart_frame.grid_columnconfigure(0, weight=1)
        # Prefill from DB
        try:
            ap = get_apartment_payment()
            if ap is not None:
                self.apart_entry.insert(0, f"{float(ap):.2f}")
        except Exception:
            pass
        save_ap_btn = ctk.CTkButton(apart_frame, text="Save apartment payment", command=self._save_apartment)
        save_ap_btn.grid(row=1, column=1, padx=8, pady=(0, 8))

        # Category limits section
        limits_frame = ctk.CTkFrame(self)
        limits_frame.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(limits_frame, text="Category limits").grid(row=0, column=0, columnspan=3, padx=8, pady=(8, 6), sticky="w")

        # Existing categories dropdown
        try:
            self.cat_values = [name for name, _ in (list_limits() or [])]
        except Exception:
            self.cat_values = []
        self.cat_var = tk.StringVar(value=self.cat_values[0] if self.cat_values else "")
        self.cat_combo = ctk.CTkOptionMenu(limits_frame, variable=self.cat_var, values=self.cat_values)
        self.cat_combo.grid(row=1, column=0, padx=8, pady=2, sticky="we")

        # Limit value entry for selected category
        self.limit_entry = ctk.CTkEntry(limits_frame, placeholder_text="Default monthly limit")
        self.limit_entry.grid(row=1, column=1, padx=8, pady=2, sticky="we")

        # Set limit button
        ctk.CTkButton(limits_frame, text="Set limit", command=self._save_limit_default).grid(row=1, column=2, padx=8, pady=2)

        limits_frame.grid_columnconfigure(0, weight=1)
        limits_frame.grid_columnconfigure(1, weight=1)

        # Separator
        sep = ctk.CTkFrame(self, height=2)
        sep.pack(fill="x", padx=14, pady=(10, 0))

        # Add Category section
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

        # Separator
        sep2 = ctk.CTkFrame(self, height=2)
        sep2.pack(fill="x", padx=14, pady=(0, 0))

        # Delete Category section
        delcat_frame = ctk.CTkFrame(self)
        delcat_frame.pack(fill="x", padx=14, pady=(10, 14))
        ctk.CTkLabel(delcat_frame, text="Delete Category").grid(row=0, column=0, columnspan=2, padx=8, pady=(8, 6), sticky="w")

        # Dropdown of existing categories
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

        # Logging section
        log_frame = ctk.CTkFrame(self)
        log_frame.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(log_frame, text="Logging").grid(row=0, column=0, padx=8, pady=(8, 6), sticky="w")
        levels = ["DEBUG","INFO","WARNING","ERROR"]
        cur = logger.level
        level_names = {10: "DEBUG", 20: "INFO", 30: "WARNING", 40: "ERROR", 50: "CRITICAL"}
        cur_name = level_names.get(cur, "INFO")
        self.log_var = tk.StringVar(value=cur_name if cur_name in levels else "INFO")
        self.log_menu = ctk.CTkOptionMenu(log_frame, variable=self.log_var, values=levels)
        self.log_menu.grid(row=0, column=1, padx=8, pady=(8, 6), sticky="w")
        ctk.CTkButton(log_frame, text="Apply level", command=self._apply_log_level).grid(row=0, column=2, padx=8, pady=(8, 6))
        ctk.CTkButton(log_frame, text="Open log file", command=self._open_log_file).grid(row=0, column=3, padx=8, pady=(8, 6))
        log_frame.grid_columnconfigure(1, weight=1)

    def _apply_log_level(self):
        lvl = self.log_var.get()
        try:
            import logging
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
                import os
                os.system(f'open "{log_file}"')
            elif os.name == 'nt':
                import os
                os.startfile(str(log_file))
            else:
                import os
                os.system(f'xdg-open "{log_file}"')
        except Exception as e:
            messagebox.showerror("Open log", f"Failed: {e}")

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

            # Update dropdowns in dialog
            try:
                self.cat_values = [n for n, _ in (list_limits() or [])]
            except Exception:
                self.cat_values = []
            self.cat_combo.configure(values=self.cat_values)
            self.del_cat_values = list(self.cat_values)
            self.del_cat_combo.configure(values=self.del_cat_values)
            self.cat_var.set(self.cat_values[0] if self.cat_values else "")
            self.del_cat_var.set(self.del_cat_values[0] if self.del_cat_values else "")

            # Update parent window
            try:
                self.parent.reload_categories()
                self.parent.refresh_table()
                self.parent.update_remaining_indicator()
                self.parent.update_summary_indicator()
            except Exception:
                pass

            # Push changes
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

        # Duplicate check (case-insensitive)
        try:
            existing_lc = [n.lower() for n, _ in (list_limits() or [])]
        except Exception:
            existing_lc = []
        if name.lower() in existing_lc:
            messagebox.showerror("Error", f"Category '{name}' already exists")
            return

        try:
            set_limit_and_apply(name, amount, self.parent.month_var.get())
            # Refresh parent category dropdown & select new category
            try:
                self.parent.reload_categories(prefer=name)
            except Exception:
                pass
            # Refresh dropdown values
            try:
                self.cat_values = [n for n, _ in (list_limits() or [])]
            except Exception:
                self.cat_values = []
            self.cat_combo.configure(values=self.cat_values)
            self.cat_var.set(name)
            # Also refresh Delete Category dropdown dynamically
            try:
                self.del_cat_values = list(self.cat_values)
            except Exception:
                self.del_cat_values = []
            if hasattr(self, 'del_cat_combo'):
                self.del_cat_combo.configure(values=self.del_cat_values)
            if hasattr(self, 'del_cat_var'):
                self.del_cat_var.set(name)
            # Clear inputs
            self.new_cat_entry.delete(0, tk.END)
            self.new_cat_limit_entry.delete(0, tk.END)
            # Push to GitHub and notify
            self.parent._push_db_best_effort("Add category")
            messagebox.showinfo("Saved", f"Category '{name}' added with default limit {amount:.2f}")
            # Refresh parent UI if needed
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
            set_limit_and_apply(name, amount, self.parent.month_var.get())
            try:
                self.parent.reload_categories()
            except Exception:
                pass
            # Keep Delete Category dropdown in sync as well
            try:
                self.cat_values = [n for n, _ in (list_limits() or [])]
                self.del_cat_values = list(self.cat_values)
                if hasattr(self, 'del_cat_combo'):
                    self.del_cat_combo.configure(values=self.del_cat_values)
                if hasattr(self, 'del_cat_var') and self.cat_values:
                    self.del_cat_var.set(self.cat_values[0])
            except Exception:
                pass
            # Refresh parent UI combos if needed
            self._refresh_parent_after_limits()
            self.parent._push_db_best_effort("Update default limit")
            messagebox.showinfo("Saved", f"Default limit for '{name}' saved: {amount:.2f}")
        except Exception as e:
            messagebox.showerror("Error", f"Cannot save limit: {e}")

    def _refresh_parent_after_limits(self):
        # Update parent category dropdowns/indicators
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
