import customtkinter as ctk
import tkinter as tk
from bd import get_current_month, prev_month, list_limits, list_months
from services.logging_config import get_logger

logger = get_logger("budget-top-panel")

class TopPanel:
    """Top panel with category/month selectors, amount input, and settings button."""

    def __init__(self, parent, on_category_change=None, on_month_change=None,
                 on_compare_month_change=None, on_settings_click=None):
        self.parent = parent
        self.on_category_change = on_category_change
        self.on_month_change = on_month_change
        self.on_compare_month_change = on_compare_month_change
        self.on_settings_click = on_settings_click

        # Create top frame
        self.top_frame = ctk.CTkFrame(parent, height=130)
        self.top_frame.pack(fill='x', padx=20, pady=(20, 10))
        self.top_frame.grid_columnconfigure(4, weight=1)

        # Initialize variables
        self.category_var = tk.StringVar(value="Food")
        self.amount_entry = None
        self.add_btn = None
        self.settings_btn = None
        self.month_var = None
        self.compare_month_var = None

        self.create_widgets()
        self.update_month_menus()

    def create_widgets(self):
        """Create all widgets in the top panel."""
        # Category selector
        self.category_menu = ctk.CTkOptionMenu(
            self.top_frame,
            variable=self.category_var,
            values=[],
            command=self.on_category_change
        )
        self.category_menu.grid(row=0, column=0, padx=10, pady=10)

        # Amount entry with validation
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

        vcmd = (self.parent.register(_validate_amount), '%d', '%P')
        self.amount_entry.configure(validate='key', validatecommand=vcmd)

        # Add button
        self.add_btn = ctk.CTkButton(self.top_frame, text="Add expenses")
        self.add_btn.grid(row=0, column=2, padx=10, pady=10)

        # Settings button
        try:
            self.top_frame.grid_columnconfigure(99, weight=1)
        except Exception:
            pass
        self.settings_btn = ctk.CTkButton(
            self.top_frame,
            text="⚙",
            height=44,
            width=54,
            font=("", 20, "bold"),
            command=self.on_settings_click
        )
        self.settings_btn.grid(row=0, column=100, padx=(10, 10), pady=8, sticky="e")

        # Month block
        self.month_block = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self.month_block.grid(row=1, column=0, columnspan=4, padx=10, pady=(0, 6), sticky="w")
        ctk.CTkLabel(self.month_block, text="Month:").grid(row=0, column=0, padx=(0, 6), pady=0, sticky="w")

        curr_m = get_current_month()
        self.month_var = tk.StringVar(value=curr_m)
        self.month_menu = ctk.CTkOptionMenu(
            self.month_block,
            variable=self.month_var,
            values=[],
            command=self.on_month_change
        )
        self.month_menu.grid(row=0, column=1, padx=(0, 12), pady=0, sticky="w")

        ctk.CTkLabel(self.month_block, text="Compare:").grid(row=0, column=2, padx=(0, 6), pady=0, sticky="w")
        self.compare_month_var = tk.StringVar(value=prev_month(curr_m))
        self.compare_month_menu = ctk.CTkOptionMenu(
            self.month_block,
            variable=self.compare_month_var,
            values=[],
            command=self.on_compare_month_change
        )
        self.compare_month_menu.grid(row=0, column=3, padx=(0, 0), pady=0, sticky="w")
        self.month_block.grid_columnconfigure(4, weight=1)

    def reload_categories(self, prefer=None):
        """Reload category list from database."""
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

        self.category_menu.configure(values=cats)
        cur = self.category_var.get()
        if prefer and prefer in cats:
            self.category_var.set(prefer)
        else:
            self.category_var.set(cur if cur in cats else cats[0])

    def update_month_menus(self):
        """Update month dropdowns with available months."""
        months = list_months()
        curr_m = get_current_month()
        if curr_m not in months:
            months.insert(0, curr_m)

        self.month_menu.configure(values=months)
        self.compare_month_menu.configure(values=months)

        # Ensure selected values are valid
        if self.month_var.get() not in months:
            self.month_var.set(curr_m)
        if self.compare_month_var.get() not in months:
            pm = prev_month(self.month_var.get())
            self.compare_month_var.set(pm if pm in months else (months[1] if len(months) > 1 else self.month_var.get()))

    def get_amount(self):
        """Get current amount from entry."""
        return self.amount_entry.get()

    def clear_amount(self):
        """Clear amount entry."""
        self.amount_entry.delete(0, tk.END)

    def get_category(self):
        """Get selected category."""
        return self.category_var.get()

    def get_month(self):
        """Get selected month."""
        return self.month_var.get()

    def get_compare_month(self):
        """Get selected compare month."""
        return self.compare_month_var.get()
