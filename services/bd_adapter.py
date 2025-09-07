"""
Adapter layer to replace bd.py functions with API calls.
This allows minimal changes to existing UI code.
"""
from services.api_client import BudgetApiClient
from typing import List, Tuple, Dict
import os

# Global API client instance
_api_client = None

def get_api_client() -> BudgetApiClient:
    """Get or create global API client instance."""
    global _api_client
    if _api_client is None:
        _api_client = BudgetApiClient()
    return _api_client

# --- Functions that replace bd.py functions ---

def get_current_month() -> str:
    """Get current month in YYYY-MM format."""
    return get_api_client().get_current_month()

def get_expenses_for_month(month: str) -> List[Tuple[int, str, float, str]]:
    """Get expenses for a specific month. Returns list of tuples: (id, category, amount, date)"""
    return get_api_client().get_expenses_for_month(month)

def add_expense(category: str, amount: float) -> Tuple[bool, float]:
    """Add expense. Returns (exceeded_limit, remaining_amount)"""
    return get_api_client().add_expense(category, amount)

def update_expense(expense_id: int, category: str, amount: float, date: str = None) -> None:
    """Update existing expense."""
    if date is None:
        # If no date provided, we need to get current date
        # This matches the original bd.py behavior
        from datetime import datetime
        date = datetime.now().strftime("%Y-%m-%d")
    get_api_client().update_expense(expense_id, category, amount, date)

def delete_expense(expense_id: int) -> None:
    """Delete expense by ID."""
    get_api_client().delete_expense(expense_id)

def get_month_report(month: str) -> Dict[str, Dict[str, float]]:
    """Get spending report for a month."""
    try:
        # API returns {category: amount} format
        spending = get_api_client().get_month_report(month)
        remaining = get_api_client().get_remaining(month)
        limits = dict(get_api_client().list_limits())
        
        # Convert to the format expected by UI: {category: {'spent': X, 'budget': Y}}
        result = {}
        all_categories = set(spending.keys()) | set(remaining.keys()) | set(limits.keys())
        
        for category in all_categories:
            spent = spending.get(category, 0.0)
            budget = limits.get(category, 0.0)
            result[category] = {
                'spent': spent,
                'budget': budget
            }
        
        return result
    except Exception as e:
        # Return empty dict on error to avoid UI crashes
        return {}

def list_months() -> List[str]:
    """Get list of months with expenses."""
    return get_api_client().list_months()

def list_limits() -> List[Tuple[str, float]]:
    """Get all category limits. Returns list of tuples: (category, limit)"""
    return get_api_client().list_limits()

def set_limit_and_apply(category: str, amount: float) -> None:
    """Set category limit and apply to current month."""
    get_api_client().set_limit_and_apply(category, amount)

def set_limit(category: str, amount: float) -> None:
    """Set category limit."""
    get_api_client().set_limit(category, amount)

def delete_category(category: str) -> int:
    """Delete category and all its expenses. Returns count of deleted expenses."""
    return get_api_client().delete_category(category)

def get_remaining(category: str, month: str) -> float:
    """Get remaining budget for a specific category in a month."""
    remaining_dict = get_api_client().get_remaining(month)
    return remaining_dict.get(category, 0.0)

# --- Additional utility functions that might be needed ---

def prev_month(month: str) -> str:
    """Get previous month in YYYY-MM format."""
    from datetime import datetime, timedelta
    try:
        date = datetime.strptime(month + "-01", "%Y-%m-%d")
        prev_date = date - timedelta(days=1)  # Go to last day of previous month
        return prev_date.strftime("%Y-%m")
    except:
        return month  # Return same month on error

# --- Removed functions (not needed in API mode) ---

def get_apartment_payment() -> float:
    """Apartment payment functionality removed in API mode."""
    return 0.0

def set_apartment_payment(amount: float) -> None:
    """Apartment payment functionality removed in API mode."""
    pass
