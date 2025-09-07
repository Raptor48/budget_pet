import matplotlib.pyplot as plt
import customtkinter as ctk
from bd import get_expenses_for_month, get_apartment_payment

def show_pie_chart(parent, month_var):
    """Show pie chart for current month expenses."""
    expenses = get_expenses_for_month(month_var.get())
    totals = {}
    for _, category, amount, _ in expenses:
        totals[category] = totals.get(category, 0) + float(amount)

    try:
        ap = get_apartment_payment()
        if ap is not None and float(ap) > 0:
            totals["Apartment payment"] = totals.get("Apartment payment", 0) + float(ap)
    except Exception:
        pass

    fig, ax = plt.subplots()
    if not totals:
        ax.text(0.5, 0.5, 'No data', ha='center', va='center')
    else:
        ax.pie(list(totals.values()), labels=list(totals.keys()), autopct='%1.1f%%', textprops={'color':'black'})
    ax.set_title("Expenses by Category")
    fig.tight_layout()
    plt.show()

def show_bar_chart(parent, month_var):
    """Show bar chart for current month expenses."""
    expenses = get_expenses_for_month(month_var.get())
    totals = {}
    for _, category, amount, _ in expenses:
        totals[category] = totals.get(category, 0) + float(amount)

    try:
        ap = get_apartment_payment()
        if ap is not None and float(ap) > 0:
            totals["Apartment payment"] = totals.get("Apartment payment", 0) + float(ap)
    except Exception:
        pass

    fig, ax = plt.subplots()
    if not totals:
        ax.text(0.5, 0.5, 'No data', ha='center', va='center')
    else:
        cats = list(totals.keys())
        vals = list(totals.values())
        x = range(len(cats))
        ax.bar(x, vals)
        ax.set_xticks(list(x))
        ax.set_xticklabels(cats, rotation=30, ha='right', color='black')
        ax.tick_params(axis='y', colors='black')
    ax.set_ylabel("Amount")
    ax.set_title("Expenses by Category")
    fig.tight_layout()
    plt.show()

def show_trends_window(parent, months, totals):
    """Show trends window with monthly totals."""
    win = ctk.CTkToplevel(parent)
    win.title("Trends")
    win.geometry("720x420")

    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

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
