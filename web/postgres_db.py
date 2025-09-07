"""
PostgreSQL database operations for FastAPI.
Replaces bd.py functionality with PostgreSQL.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Tuple, Dict, Optional
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)

# Database connection
def get_db_connection():
    """Get PostgreSQL database connection."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set")
    
    # Log the connection URL (without password for security)
    safe_url = database_url.split('@')[1] if '@' in database_url else database_url
    logger.info(f"Connecting to PostgreSQL: postgresql://***@{safe_url}")
    
    return psycopg2.connect(database_url)

def _today_iso() -> str:
    """Get today's date in YYYY-MM-DD format."""
    today = date.today()
    return f"{today.year}-{today.month:02d}-{today.day:02d}"

def _month_from_date(date_str: str) -> str:
    """Convert YYYY-MM-DD to YYYY-MM format."""
    try:
        # Parse YYYY-MM-DD format
        year, month, day = date_str.split('-')
        return f"{year}-{month.zfill(2)}"
    except:
        # Fallback for MM-DD-YYYY format (legacy)
        try:
            month, day, year = date_str.split('-')
            return f"{year}-{month.zfill(2)}"
        except:
            return date_str[:7]

def _validate_amount(value: float, what: str = "amount") -> float:
    """Validate and return amount."""
    try:
        v = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{what} must be a number")
    
    if v < 0:
        raise ValueError(f"{what} must be non-negative")
    return v

# Expenses CRUD
def get_expenses_for_month(month: str) -> List[Tuple[int, str, float, str]]:
    """Get expenses for a specific month."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # month format: YYYY-MM, find dates like YYYY-MM-DD or MM-DD-YYYY
            year, month_num = month.split('-')
            cursor.execute("""
                SELECT id, category, amount, date 
                FROM expenses 
                WHERE date LIKE %s OR date LIKE %s
                ORDER BY date DESC, id DESC
            """, (f"{year}-{month_num.zfill(2)}-%", f"{month_num.zfill(2)}-%{year}"))
            rows = cursor.fetchall()
            return [(int(r[0]), r[1], float(r[2]), r[3]) for r in rows]

def add_expense(category: str, amount: float, date: Optional[str] = None) -> Tuple[bool, float]:
    """Add expense. Returns (exceeded, remaining_after)."""
    amount = _validate_amount(amount, "amount")
    expense_date = date or _today_iso()
    month = _month_from_date(expense_date)
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Insert expense
            cursor.execute("""
                INSERT INTO expenses(category, amount, date) 
                VALUES(%s, %s, %s) 
                RETURNING id
            """, (category, amount, expense_date))
            conn.commit()
            
            # Get remaining budget
            remaining = get_remaining(category, month)
            exceeded = remaining < 0
            return exceeded, remaining

def update_expense(expense_id: int, category: str, amount: float) -> None:
    """Update an expense."""
    amount = _validate_amount(amount, "amount")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE expenses 
                SET category=%s, amount=%s 
                WHERE id=%s
            """, (category, amount, expense_id))
            conn.commit()

def delete_expense(expense_id: int) -> None:
    """Delete an expense."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM expenses WHERE id=%s", (expense_id,))
            conn.commit()

# Limits
def list_limits() -> List[Tuple[str, float]]:
    """Get all category limits."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT category, default_limit FROM category_limits")
            return [(row[0], float(row[1])) for row in cursor.fetchall()]

def set_limit_and_apply(category: str, amount: float, month: str) -> None:
    """Set category limit and apply to monthly budget."""
    amount = _validate_amount(amount, "limit")
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Update category limit
            cursor.execute("""
                INSERT INTO category_limits(category, default_limit) 
                VALUES(%s, %s) 
                ON CONFLICT (category) 
                DO UPDATE SET default_limit = EXCLUDED.default_limit
            """, (category, amount))
            
            # Update monthly budget
            cursor.execute("""
                INSERT INTO monthly_budgets(month, category, budget_limit) 
                VALUES(%s, %s, %s) 
                ON CONFLICT (month, category) 
                DO UPDATE SET budget_limit = EXCLUDED.budget_limit
            """, (month, category, amount))
            
            conn.commit()

def delete_category(category: str) -> None:
    """Delete category and all its expenses."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Delete expenses
            cursor.execute("DELETE FROM expenses WHERE category=%s", (category,))
            # Delete category limit
            cursor.execute("DELETE FROM category_limits WHERE category=%s", (category,))
            # Delete monthly budgets
            cursor.execute("DELETE FROM monthly_budgets WHERE category=%s", (category,))
            conn.commit()

# Reports
def get_month_report(month: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """Get spending report for a month."""
    if month is None:
        month = _month_from_date(_today_iso())
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Get expenses for the month
            # month format: YYYY-MM, find dates like YYYY-MM-DD or MM-DD-YYYY
            year, month_num = month.split('-')
            cursor.execute("""
                SELECT category, SUM(amount) as spent 
                FROM expenses 
                WHERE date LIKE %s OR date LIKE %s
                GROUP BY category
            """, (f"{year}-{month_num.zfill(2)}-%", f"{month_num.zfill(2)}-%{year}"))
            expenses = {row[0]: float(row[1]) for row in cursor.fetchall()}
            
            # Get budget limits for the month
            cursor.execute("""
                SELECT category, budget_limit 
                FROM monthly_budgets 
                WHERE month = %s
            """, (month,))
            budgets = {row[0]: float(row[1]) for row in cursor.fetchall()}
            
            # Get default limits for categories not in monthly budgets
            cursor.execute("""
                SELECT cl.category, cl.default_limit 
                FROM category_limits cl 
                LEFT JOIN monthly_budgets mb ON cl.category = mb.category AND mb.month = %s
                WHERE mb.category IS NULL
            """, (month,))
            default_limits = {row[0]: float(row[1]) for row in cursor.fetchall()}
            
            # Combine budgets and default limits
            all_budgets = {**default_limits, **budgets}
            
            # Build result
            result = {}
            all_categories = set(expenses.keys()) | set(all_budgets.keys())
            
            for category in all_categories:
                spent = expenses.get(category, 0.0)
                budget = all_budgets.get(category, 0.0)
                remaining = budget - spent
                
                result[category] = {
                    "spent": spent,
                    "budget": budget,
                    "remaining": remaining,
                    "rolled_over": 0.0  # Default value for rolled_over
                }
            
            return result

def get_remaining(category: str, month: str) -> float:
    """Get remaining budget for a category in a month."""
    report = get_month_report(month)
    category_data = report.get(category, {})
    return category_data.get("remaining", 0.0)

def get_current_month() -> str:
    """Get current month in YYYY-MM format."""
    return _month_from_date(_today_iso())

def prev_month(month: str) -> str:
    """Get previous month in YYYY-MM format."""
    try:
        year, month_num = map(int, month.split("-"))
        if month_num == 1:
            return f"{year-1}-12"
        return f"{year}-{month_num-1:02d}"
    except:
        return month

def rename_category(old_name: str, new_name: str) -> None:
    """Rename a category in all tables."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Update category_limits table
            cursor.execute("""
                UPDATE category_limits 
                SET category = %s 
                WHERE category = %s
            """, (new_name, old_name))
            
            # Update monthly_budgets table
            cursor.execute("""
                UPDATE monthly_budgets 
                SET category = %s 
                WHERE category = %s
            """, (new_name, old_name))
            
            # Update expenses table
            cursor.execute("""
                UPDATE expenses 
                SET category = %s 
                WHERE category = %s
            """, (new_name, old_name))
            
            conn.commit()
