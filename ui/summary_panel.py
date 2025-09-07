import customtkinter as ctk
import tkinter as tk
from services.bd_adapter import get_month_report, prev_month
from services.logging_config import get_logger

logger = get_logger("budget-summary")

class SummaryPanel:
    """Right panel showing category summary and progress bar."""

    def __init__(self, parent, on_open_comparison=None, on_open_trends=None):
        self.parent = parent
        self.on_open_comparison = on_open_comparison
        self.on_open_trends = on_open_trends

        # Create summary frame
        self.right_summary_frame = ctk.CTkFrame(parent)
        self.right_summary_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        # Initialize variables
        self.sum_category_var = tk.StringVar(value="Category: –")
        self.sum_budget_var = tk.StringVar(value="Budget: –")
        self.sum_spent_var = tk.StringVar(value="Spent: –")
        self.sum_remaining_var = tk.StringVar(value="Remaining: –")
        self.sum_rolled_var = tk.StringVar(value="Rolled over: –")
        self.sum_vs_var = tk.StringVar(value="")

        self.usage_progress = None
        self.usage_default_color = None
        self.sum_remaining_label = None
        self.sum_remaining_default_color = None

        self.create_widgets()

    def create_widgets(self):
        """Create all summary widgets."""
        # Title
        title = ctk.CTkLabel(self.right_summary_frame, text="Summary", font=("", 16, "bold"))
        title.grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 6))

        # Summary labels
        ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_category_var).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=10, pady=2
        )
        ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_budget_var).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=10, pady=2
        )
        ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_spent_var).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=10, pady=2
        )

        self.sum_remaining_label = ctk.CTkLabel(
            self.right_summary_frame, textvariable=self.sum_remaining_var
        )
        self.sum_remaining_label.grid(row=4, column=0, columnspan=2, sticky="w", padx=10, pady=2)
        self.sum_remaining_default_color = self.sum_remaining_label.cget("text_color")

        ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_rolled_var).grid(
            row=5, column=0, columnspan=2, sticky="w", padx=10, pady=2
        )

        self.sum_vs_label = ctk.CTkLabel(self.right_summary_frame, textvariable=self.sum_vs_var)
        self.sum_vs_label.grid(row=6, column=0, columnspan=2, sticky="w", padx=10, pady=(6, 2))

        # Progress bar
        self.usage_progress = ctk.CTkProgressBar(self.right_summary_frame)
        self.usage_progress.set(0)
        self.usage_progress.grid(row=7, column=0, columnspan=2, sticky="we", padx=10, pady=(8, 12))

        self.usage_default_color = self.usage_progress.cget("progress_color")

        # Configure grid
        self.right_summary_frame.grid_columnconfigure(0, weight=1)
        self.right_summary_frame.grid_columnconfigure(1, weight=1)

        # Buttons
        btn = ctk.CTkButton(
            self.right_summary_frame,
            text="Open Comparison",
            command=self.on_open_comparison
        )
        btn.grid(row=8, column=0, sticky="w", padx=10, pady=(4, 10))

        trends_btn = ctk.CTkButton(
            self.right_summary_frame,
            text="Trends",
            command=self.on_open_trends
        )
        trends_btn.grid(row=8, column=1, sticky="e", padx=10, pady=(4, 10))

    def update_summary(self, category=None, month=None, compare_month=None):
        """Update summary for given category and month."""
        try:
            if not category or not month:
                # Reset to defaults
                self.sum_category_var.set("Category: –")
                self.sum_budget_var.set("Budget: –")
                self.sum_spent_var.set("Spent: –")
                self.sum_remaining_var.set("Remaining: –")
                self.sum_rolled_var.set("Rolled over: –")
                self.sum_vs_var.set("")
                self.usage_progress.set(0)
                if self.sum_remaining_label:
                    self.sum_remaining_label.configure(text_color=self.sum_remaining_default_color)
                if self.usage_progress:
                    self.usage_progress.configure(progress_color=self.usage_default_color)
                return

            report = get_month_report(month)
            data = report.get(category)

            self.sum_category_var.set(f"Category: {category}")

            if not data:
                # No data for this category
                self.sum_budget_var.set("Budget: $0.00")
                self.sum_spent_var.set("Spent: $0.00")
                self.sum_remaining_var.set("Remaining: $0.00")
                self.sum_rolled_var.set("Rolled over: $0.00")
                self.sum_vs_var.set("")
                self.usage_progress.set(0)
                if self.sum_remaining_label:
                    self.sum_remaining_label.configure(text_color=self.sum_remaining_default_color)
                if self.usage_progress:
                    self.usage_progress.configure(progress_color=self.usage_default_color)
                return

            budget = float(data.get("budget", 0.0))
            spent = float(data.get("spent", 0.0))
            remaining = float(data.get("remaining", 0.0))
            rolled = float(data.get("rolled_over", 0.0))

            self.sum_budget_var.set(f"Budget: ${budget:.2f}")
            self.sum_spent_var.set(f"Spent: ${spent:.2f}")
            self.sum_remaining_var.set(f"Remaining: ${remaining:.2f}")
            self.sum_rolled_var.set(f"Rolled over: ${rolled:.2f}")

            # Update progress bar and color
            usage = 0.0
            if budget > 0:
                usage = min(max(spent / budget, 0.0), 1.0)

            self.usage_progress.set(usage)

            if budget > 0 and usage >= 0.9:
                self.usage_progress.configure(progress_color="#ff4d4f")
                self.sum_remaining_label.configure(text_color="#ff4d4f")  # red
            else:
                self.usage_progress.configure(progress_color=self.usage_default_color)
                self.sum_remaining_label.configure(text_color=self.sum_remaining_default_color)

            # Compare with another month
            if compare_month:
                try:
                    cmp_report = get_month_report(compare_month)
                    cmp_spent = float(cmp_report.get(category, {}).get("spent", 0.0))
                    delta = spent - cmp_spent
                    pct = (delta / cmp_spent * 100.0) if cmp_spent > 0 else 0.0
                    self.sum_vs_var.set(f"vs {compare_month}: Δ {delta:+.2f} ({pct:+.1f}%)")
                except Exception:
                    self.sum_vs_var.set("")
            else:
                self.sum_vs_var.set("")

        except Exception as e:
            logger.error("Update summary failed: %s", e)
            # Reset on error
            self.sum_category_var.set("Category: –")
            self.sum_budget_var.set("Budget: –")
            self.sum_spent_var.set("Spent: –")
            self.sum_remaining_var.set("Remaining: –")
            self.sum_rolled_var.set("Rolled over: –")
            self.sum_vs_var.set("")
            self.usage_progress.set(0)
            if self.sum_remaining_label:
                self.sum_remaining_label.configure(text_color=self.sum_remaining_default_color)
            if self.usage_progress:
                self.usage_progress.configure(progress_color=self.usage_default_color)
