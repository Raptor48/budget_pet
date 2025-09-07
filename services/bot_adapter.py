"""
Adapter layer for Telegram bot to replace bd.py functions with async API calls.
This allows minimal changes to existing bot code.
"""
from services.api_client import AsyncBudgetApiClient
from typing import List, Tuple, Dict
import asyncio

# Global async API client instance
_async_api_client = None

def get_async_api_client() -> AsyncBudgetApiClient:
    """Get or create global async API client instance."""
    global _async_api_client
    if _async_api_client is None:
        _async_api_client = AsyncBudgetApiClient()
    return _async_api_client

# --- Async functions that replace bd.py functions for bot ---

async def add_expense(category: str, amount: float) -> Tuple[bool, float]:
    """Add expense. Returns (exceeded_limit, remaining_amount)"""
    return await get_async_api_client().add_expense(category, amount)

async def get_month_report(month: str) -> Dict[str, Dict[str, float]]:
    """Get spending report for a month."""
    try:
        # Get raw API data
        api_data = await get_async_api_client().get_month_report(month)
        
        # Convert to the format expected by bot: {category: {'spent': X, 'budget': Y}}
        spending = api_data.get('spending_by_category', {})
        remaining = api_data.get('remaining_by_category', {})
        
        # Get limits
        limits_list = await get_async_api_client().list_limits()
        limits = {limit['category']: limit['amount'] for limit in limits_list}
        
        # Build result
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
        # Return empty dict on error to avoid bot crashes
        return {}

async def get_remaining(category: str, month: str) -> float:
    """Get remaining budget for a specific category in a month."""
    remaining_dict = await get_async_api_client().get_remaining(month)
    return remaining_dict.get(category, 0.0)

async def list_limits() -> List[Tuple[str, float]]:
    """Get all category limits. Returns list of tuples: (category, limit)"""
    limits_list = await get_async_api_client().list_limits()
    return [(limit['category'], limit['amount']) for limit in limits_list]

async def set_limit(category: str, amount: float) -> None:
    """Set category limit."""
    await get_async_api_client().set_limit(category, amount)

def get_current_month() -> str:
    """Get current month in YYYY-MM format."""
    return get_async_api_client().get_current_month()

# --- Helper functions for bot ---

async def get_expenses_for_month(month: str) -> List[Dict]:
    """Get expenses for a specific month."""
    return await get_async_api_client().get_expenses_for_month(month)
