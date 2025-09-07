import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import csv
import customtkinter as ctk
from bd import get_expenses_for_month, delete_expense
from services.search_filter import matches
from ui.widgets import ToolTip
from services.logging_config import get_logger

logger = get_logger("budget-table")

class TableView:
    """Table view for displaying expenses with sorting and filtering."""

    def __init__(self, parent, on_selection_change=None, on_double_click=None):
        self.parent = parent
        self.on_selection_change = on_selection_change
        self.on_double_click = on_double_click
        self.sort_column = None
        self.sort_reverse = False
        self.search_var = None

        # Create table frame
        self.left_table_frame = ctk.CTkFrame(parent)
        self.left_table_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self.create_table()
        self.create_toolbar()

    def create_table(self):
        """Create the main table widget."""
        columns = ('id', 'category', 'amount', 'date')
        self.table = ttk.Treeview(
            self.left_table_frame,
            columns=columns,
            show='headings',
            height=20
        )

        self.table.heading('id', text='id')
        self.table.heading('category', text='Category', command=lambda: self.sort_by('category'))
        self.table.heading('amount', text='Amount', command=lambda: self.sort_by('amount'))
        self.table.heading('date', text='Date', command=lambda: self.sort_by('date'))

        # Hide id column
        self.table.column('id', width=0, stretch=False)
        self.table.column('category', width=220)
        self.table.column('amount', width=120, anchor='e')
        self.table.column('date', width=140)

        self.table.pack(fill='both', expand=True)

        # Bind events
        self.table.bind('<Double-1>', self.on_double_click)
        self.table.bind('<<TreeviewSelect>>', self.on_selection_change)

        # Context menu for deletion
        self.table_menu = tk.Menu(self.parent, tearoff=0)
        self.table_menu.add_command(label="Delete record", command=self.delete_selected_expense)

        # Right-click binding
        self.table.bind('<Button-3>', self.show_table_menu)
        self.table.bind('<Control-Button-1>', self.show_table_menu)

        # Row colors
        self.table.tag_configure('oddrow', background='#b7b7b7')
        self.table.tag_configure('evenrow', background='#dddddd')

    def create_toolbar(self):
        """Create toolbar with search and sync buttons."""
        toolbar = ctk.CTkFrame(self.left_table_frame)
        toolbar.pack(fill='x', padx=0, pady=(0, 4))

        self.search_var = tk.StringVar()
        search_entry = ctk.CTkEntry(toolbar, textvariable=self.search_var, placeholder_text="Search category...")
        search_entry.pack(side='left', padx=(0, 8))
        search_entry.bind('<KeyRelease>', lambda e: self.refresh_table())

        sync_btn = ctk.CTkButton(toolbar, text="Sync now", width=86, command=self._manual_sync)
        sync_btn.pack(side='left', padx=(0, 6))
        ToolTip(sync_btn, "Pull latest DB from GitHub")

        export_btn = ctk.CTkButton(toolbar, text="Export CSV", width=96, command=self._export_csv)
        export_btn.pack(side='left')
        ToolTip(export_btn, "Export current month to CSV")

    def refresh_table(self, month=None, search_query=None):
        """Refresh table data with optional filtering."""
        # Clear existing items
        for row in self.table.get_children():
            self.table.delete(row)

        if month is None:
            return

        expenses = get_expenses_for_month(month)

        # Apply search filter
        query = (self.search_var.get().strip() if self.search_var else '') if search_query is None else search_query
        if query:
            expenses = [e for e in expenses if matches(e, query)]

        # Apply sorting
        if self.sort_column:
            idx = {'id': 0, 'category': 1, 'amount': 2, 'date': 3}[self.sort_column]
            expenses.sort(key=lambda x: x[idx], reverse=self.sort_reverse)

        # Add rows to table
        for expense in expenses:
            if len(expense) == 4:
                tag = 'evenrow' if len(self.table.get_children()) % 2 == 0 else 'oddrow'
                self.table.insert('', tk.END, values=expense, tags=(tag,))

    def sort_by(self, col):
        """Sort table by column."""
        if self.sort_column == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = col
            self.sort_reverse = False
        # Trigger refresh with current month
        self.refresh_table()

    def show_table_menu(self, event):
        """Show context menu on right-click."""
        row_id = self.table.identify_row(event.y)
        if row_id:
            self.table.selection_set(row_id)
            try:
                self.table_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.table_menu.grab_release()

    def delete_selected_expense(self):
        """Delete selected expense."""
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
            self.refresh_table()  # Will need month parameter
        except Exception as e:
            logger.error("Delete expense failed: %s", e)
            messagebox.showerror("Error", f"Cannot delete: {e}")

    def _manual_sync(self):
        """Manual sync placeholder - will be connected to GitHub sync."""
        # This will be connected to the main window's sync method
        pass

    def _export_csv(self, month=None):
        """Export current month to CSV."""
        try:
            if month is None:
                return
            path = filedialog.asksaveasfilename(
                defaultextension='.csv',
                filetypes=[('CSV','*.csv')],
                initialfile=f"expenses_{month}.csv"
            )
            if not path:
                return

            expenses = get_expenses_for_month(month)
            # Apply current filter
            query = (self.search_var.get().strip().lower() if self.search_var else '')
            if query:
                expenses = [e for e in expenses if query in str(e[1]).lower()]

            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['id','category','amount','date'])
                for row in expenses:
                    w.writerow(row)
            messagebox.showinfo("Export", f"Saved to {path}")
        except Exception as e:
            logger.error("Export failed: %s", e)
            messagebox.showerror("Export", f"Failed: {e}")

    def get_selected_expense(self):
        """Get data for selected expense."""
        sel = self.table.selection()
        if not sel:
            return None
        row = self.table.item(sel[0])['values']
        if len(row) == 4:
            expense_id, category, amount, date = row
            return expense_id, category, amount, date
        return None
