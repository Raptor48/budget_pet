"""
Adapter layer for Telegram bot to replace bd.py functions with async API calls.
This allows minimal changes to existing bot code.
"""
from services.api_client import AsyncBudgetApiClient
from typing import List, Tuple, Dict
import asyncio
import logging

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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
    try:
        logger.info(f"Bot adapter: Adding expense {category}=${amount}")
        result = await get_async_api_client().add_expense(category, amount)
        logger.info(f"Bot adapter: Add expense result: {result}")
        return result
    except Exception as e:
        logger.error(f"Bot adapter: Failed to add expense {category}=${amount}: {e}")
        # Return default values to prevent bot crash
        return False, 0.0

async def get_month_report(month: str) -> Dict[str, Dict[str, float]]:
    """Get spending report for a month."""
    try:
        logger.info(f"Bot adapter: Getting month report for {month}")
        # Get raw API data
        api_data = await get_async_api_client().get_month_report(month)
        logger.info(f"Bot adapter: API returned report data: {api_data}")
        
        # FastAPI returns: {"report": {"category": {"spent": X, "budget": Y, "remaining": Z}}}
        report_data = api_data.get('report', {})
        
        # Convert to the format expected by bot: {category: {'spent': X, 'budget': Y}}
        result = {}
        for category, data in report_data.items():
            result[category] = {
                'spent': data.get('spent', 0.0),
                'budget': data.get('budget', 0.0)
            }
        
        logger.info(f"Bot adapter: Converted report: {result}")
        return result
    except Exception as e:
        logger.error(f"Bot adapter: Failed to get month report for {month}: {e}")
        # Return empty dict on error to avoid bot crashes
        return {}

async def get_remaining(category: str, month: str) -> float:
    """Get remaining budget for a specific category in a month."""
    try:
        # Get full report data
        api_data = await get_async_api_client().get_month_report(month)
        report_data = api_data.get('report', {})
        category_data = report_data.get(category, {})
        return category_data.get('remaining', 0.0)
    except Exception:
        return 0.0

async def list_limits() -> List[Tuple[str, float]]:
    """Get all category limits. Returns list of tuples: (category, limit)"""
    limits_list = await get_async_api_client().list_limits()
    return [(limit['category'], limit['default_limit']) for limit in limits_list]

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
