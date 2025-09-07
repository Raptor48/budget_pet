import customtkinter as ctk
import tkinter as tk
from pathlib import Path
from datetime import datetime
import atexit
from services.api_client import BudgetApiClient
from services.bd_adapter import (
    get_current_month, get_remaining, add_expense, get_month_report,
    list_months, get_expenses_for_month, delete_expense, update_expense
)
from services.status import StatusManager
from services.logging_config import get_logger
from ui.top_panel import TopPanel
from ui.table_view import TableView
from ui.summary_panel import SummaryPanel
from ui.dialogs import SettingsDialog
from ui.charts import show_pie_chart, show_bar_chart, show_trends_window
from ui.widgets import ToolTip

logger = get_logger("budget-main")

class BudgetApp(ctk.CTk):
    """Main application window coordinating all UI components."""

    def __init__(self, api_client=None, logger=None):
        super().__init__()

        self.api_client = api_client or BudgetApiClient()
        self.logger = logger or get_logger("budget")
        self.status_manager = StatusManager()

        # Initialize window
        self.title("Family Budget (API Mode)")
        self.geometry("750x720")
        self.resizable(True, True)

        # Initialize components
        self.top_panel = None
        self.table_view = None
        self.summary_panel = None

        # State
        self._closed = False

        # Create UI
        self.create_layout()
        self.setup_event_handlers()

        # Initial data load
        self.refresh_all()

    def create_layout(self):
        """Create main layout with panels."""
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Main container
        self.main_container = ctk.CTkFrame(self)
        self.main_container.pack(fill='both', expand=True, padx=20, pady=(0, 20))
        self.main_container.grid_columnconfigure(0, weight=3)
        self.main_container.grid_columnconfigure(1, weight=2)
        self.main_container.grid_rowconfigure(0, weight=1)

        # Create panels
        self.create_bottom_container()

        # Status bar
        self.status_var = tk.StringVar(value=self.status_manager.get_status_text())
        self.status = ctk.CTkLabel(self, textvariable=self.status_var, anchor="w")
        self.status.pack(fill='x', side='bottom')

        # Charts buttons in top panel
        self.create_chart_buttons()

    def create_bottom_container(self):
        """Create bottom container with table and summary."""
        # Left table frame
        self.left_table_frame = ctk.CTkFrame(self.main_container)
        self.left_table_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # Right summary frame
        self.right_summary_frame = ctk.CTkFrame(self.main_container)
        self.right_summary_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        # Create panels
        self.top_panel = TopPanel(
            self.left_table_frame,
            on_category_change=self.on_category_change,
            on_month_change=self.on_month_change,
            on_compare_month_change=self.on_compare_month_change,
            on_settings_click=self.open_settings
        )

        self.table_view = TableView(
            self.left_table_frame,
            on_selection_change=self.on_table_selection_change,
            on_double_click=self.on_table_double_click
        )

        self.summary_panel = SummaryPanel(
            self.right_summary_frame,
            on_open_comparison=self.show_comparison_window,
            on_open_trends=self.show_trends_window
        )

    def create_chart_buttons(self):
        """Create chart buttons in top panel."""
        self.visual_frame = ctk.CTkFrame(self.top_panel.top_frame)
        self.visual_frame.grid(row=2, column=0, columnspan=4, pady=(4, 4), sticky="w")

        self.pie_btn = ctk.CTkButton(
            self.visual_frame, text="🥧", width=36, height=32,
            command=self.show_pie_chart
        )
        self.pie_btn.grid(row=0, column=0, padx=(10, 6))
        ToolTip(self.pie_btn, "Pie chart")

        self.bar_btn = ctk.CTkButton(
            self.visual_frame, text="📊", width=36, height=32,
            command=self.show_bar_chart
        )
        self.bar_btn.grid(row=0, column=1, padx=(0, 10))
        ToolTip(self.bar_btn, "Bar chart")

    def setup_event_handlers(self):
        """Setup event handlers and timers."""
        # Window close handler
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        atexit.register(self._atexit_push)

        # Connect top panel buttons
        self.top_panel.add_btn.configure(command=self.add_expense_btn)

        # API mode - no periodic sync needed

    def on_category_change(self, value):
        """Handle category selection change."""
        self.update_remaining_indicator()
        self.update_summary_indicator()

    def on_month_change(self, value):
        """Handle month selection change."""
        self.refresh_table()
        self.update_remaining_indicator()
        self.update_summary_indicator()
        self.top_panel.update_month_menus()

    def on_compare_month_change(self, value):
        """Handle compare month selection change."""
        self.update_summary_indicator()

    def on_table_selection_change(self, event):
        """Handle table row selection."""
        expense = self.table_view.get_selected_expense()
        if expense:
            _, category, _, _ = expense
            self.top_panel.category_var.set(category)
            self.update_remaining_indicator()
            self.update_summary_indicator()

    def on_table_double_click(self, event):
        """Handle table double-click."""
        expense = self.table_view.get_selected_expense()
        if expense:
            expense_id, category, amount, date = expense
            from ui.dialogs import EditDialog
            EditDialog(self, expense_id, category, amount, date, self.edit_callback)

    def add_expense_btn(self):
        """Add expense button handler."""
        category = self.top_panel.get_category()
        amount_text = self.top_panel.get_amount()

        try:
            amount = float(amount_text)
            self.logger.info("Add expense: %s %.2f", category, amount)

            exceeded, remaining = add_expense(category, amount)

            if exceeded:
                tk.messagebox.showwarning(
                    "Budget limit",
                    f"Limit exceeded for {category}. Remaining: {remaining:.2f}"
                )

            self.top_panel.clear_amount()
            self.refresh_table()
            self.update_remaining_indicator()
            self.update_summary_indicator()
            self.top_panel.update_month_menus()

            # Threshold notifications
            try:
                rep = get_month_report(self.top_panel.get_month()).get(category, {})
                budget = float(rep.get('budget', 0.0))
                spent = float(rep.get('spent', 0.0))
                if budget > 0:
                    usage = spent / budget
                    for thr, label in [(0.5,'50'),(0.75,'75'),(0.9,'90')]:
                        if usage >= thr:
                            tk.messagebox.showwarning(
                                'Budget threshold',
                                f"{category}: reached {int(thr*100)}% of monthly limit"
                            )
            except Exception:
                pass

            # Data automatically saved via API

        except ValueError:
            self.logger.error("Add expense failed: not a number: %r", amount_text)
            self.top_panel.amount_entry.configure(border_color="#ff4d4f")
            self.after(1500, lambda: self.top_panel.amount_entry.configure(border_color=None))
            return
        except Exception as e:
            self.logger.error("Add expense failed: %s", e)
            tk.messagebox.showerror("Error", f"Can't save the expense: {e}")

    def edit_callback(self, expense_id, new_category, new_amount):
        """Handle expense edit from dialog."""
        try:
            self.logger.info("Edit expense id=%s -> (%s, %.2f)", expense_id, new_category, float(new_amount))
            update_expense(expense_id, new_category, float(new_amount))
            self.refresh_table()
            self.update_remaining_indicator()
            self.update_summary_indicator()
            # Data automatically saved via API
        except Exception as e:
            self.logger.error("Edit expense failed: %s", e)
            tk.messagebox.showerror("Error", f"Failed to update: {e}")

    def open_settings(self):
        """Open settings dialog."""
        try:
            SettingsDialog(self)
        except Exception as e:
            self.logger.error("Open settings failed: %s", e)
            tk.messagebox.showerror("Error", f"Cannot open settings: {e}")

    def show_pie_chart(self):
        """Show pie chart."""
        show_pie_chart(self, self.top_panel.month_var)

    def show_bar_chart(self):
        """Show bar chart."""
        show_bar_chart(self, self.top_panel.month_var)

    def show_comparison_window(self):
        """Show comparison window."""
        curr_m = self.top_panel.get_month()
        cmp_m = self.top_panel.get_compare_month()
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

    def show_trends_window(self):
        """Show trends window."""
        months = list_months()
        totals = []
        for m in months:
            rep = get_month_report(m)
            total_spent = sum(float(d.get('spent',0.0)) for d in rep.values())
            totals.append((m, total_spent))

        show_trends_window(self, months, totals)

    def refresh_all(self):
        """Refresh all components."""
        self.top_panel.reload_categories()
        self.top_panel.update_month_menus()
        self.refresh_table()
        self.update_remaining_indicator()
        self.update_summary_indicator()

    def refresh_table(self):
        """Refresh expense table."""
        month = self.top_panel.get_month() if self.top_panel else get_current_month()
        self.table_view.refresh_table(month)

    def update_remaining_indicator(self):
        """Update remaining budget indicator."""
        try:
            if not self.top_panel:
                return
            category = self.top_panel.get_category()
            remaining = get_remaining(category, self.top_panel.get_month())
            # Update remaining label in top panel
            # This would need to be added to TopPanel
        except Exception:
            pass

    def update_summary_indicator(self):
        """Update summary panel."""
        if not self.top_panel or not self.summary_panel:
            return
        category = self.top_panel.get_category()
        month = self.top_panel.get_month()
        compare_month = self.top_panel.get_compare_month()
        self.summary_panel.update_summary(category, month, compare_month)

    # GitHub sync methods removed - using API mode

    def _set_status(self, text: str):
        """Update status display."""
        self.status_manager.set_status(text)
        self.status_var.set(self.status_manager.get_status_text())

    def on_close(self):
        """Handle window close."""
        self._closed = True
        self.logger.info("Closing app...")
        try:
            self.logger.info("Closed app")
        finally:
            try:
                for h in self.logger.handlers:
                    try:
                        h.flush()
                    except Exception:
                        pass
            except Exception:
                pass
            self.destroy()

    def _atexit_push(self):
        """No-op in API mode."""
        pass
