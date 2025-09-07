"""
API client for communicating with FastAPI backend.
Replaces direct SQLite operations with HTTP requests.
"""
import requests
import asyncio
import aiohttp
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
import os
from services.logging_config import get_logger

logger = get_logger("api-client")

class BudgetApiClient:
    """Synchronous API client for Desktop GUI."""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("API_BASE_URL", "https://fastapi-production-eadf.up.railway.app")
        self.session = requests.Session()
        self.session.timeout = 30
        
    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make HTTP request with error handling."""
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {method} {url} - {e}")
            raise RuntimeError(f"API request failed: {e}")
    
    # --- Expenses ---
    
    def get_expenses_for_month(self, month: str) -> List[Tuple[int, str, float, str]]:
        """Get expenses for a specific month. Returns list of tuples: (id, category, amount, date)"""
        data = self._request("GET", "/expenses", params={"month": month})
        return [(exp["id"], exp["category"], exp["amount"], exp["date"]) for exp in data]
    
    def add_expense(self, category: str, amount: float) -> Tuple[bool, float]:
        """Add expense. Returns (exceeded_limit, remaining_amount)"""
        data = self._request("POST", "/expenses", json={
            "category": category,
            "amount": amount
        })
        return data["exceeded"], data["remaining"]
    
    def update_expense(self, expense_id: int, category: str, amount: float, date: str) -> None:
        """Update existing expense."""
        self._request("PUT", f"/expenses/{expense_id}", json={
            "category": category,
            "amount": amount,
            "date": date
        })
    
    def delete_expense(self, expense_id: int) -> None:
        """Delete expense by ID."""
        self._request("DELETE", f"/expenses/{expense_id}")
    
    # --- Limits ---
    
    def list_limits(self) -> List[Tuple[str, float]]:
        """Get all category limits. Returns list of tuples: (category, limit)"""
        data = self._request("GET", "/limits")
        return [(limit["category"], limit["amount"]) for limit in data]
    
    def set_limit_and_apply(self, category: str, amount: float) -> None:
        """Set category limit and apply to current month."""
        self._request("POST", "/limits", json={
            "category": category,
            "amount": amount
        })
    
    def set_limit(self, category: str, amount: float) -> None:
        """Set category limit (alias for set_limit_and_apply)."""
        self.set_limit_and_apply(category, amount)
    
    def delete_category(self, category: str) -> int:
        """Delete category and all its expenses. Returns count of deleted expenses."""
        data = self._request("DELETE", f"/categories/{category}")
        return data.get("deleted_expenses", 0)
    
    # --- Reports ---
    
    def get_month_report(self, month: str) -> Dict[str, float]:
        """Get spending report for a month. Returns dict: {category: amount}"""
        data = self._request("GET", f"/reports/{month}")
        return data["spending_by_category"]
    
    def get_remaining(self, month: str) -> Dict[str, float]:
        """Get remaining budget for each category. Returns dict: {category: remaining}"""
        data = self._request("GET", f"/reports/{month}")
        return data["remaining_by_category"]
    
    # --- Utility ---
    
    def get_current_month(self) -> str:
        """Get current month in YYYY-MM format."""
        return datetime.now().strftime("%Y-%m")
    
    def list_months(self) -> List[str]:
        """Get list of months with expenses."""
        # Generate last 12 months since there's no /months endpoint
        from datetime import datetime, timedelta
        months = []
        current = datetime.now()
        for i in range(12):
            month_date = current - timedelta(days=i*30)
            months.append(month_date.strftime("%Y-%m"))
        return sorted(set(months), reverse=True)


class AsyncBudgetApiClient:
    """Asynchronous API client for Telegram Bot."""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("API_BASE_URL", "https://fastapi-production-eadf.up.railway.app")
        
    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make async HTTP request with error handling."""
        url = f"{self.base_url}{endpoint}"
        timeout = aiohttp.ClientTimeout(total=30)
        
        try:
            # Create SSL context that doesn't verify certificates for Railway.app
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.request(method, url, **kwargs) as response:
                    response.raise_for_status()
                    return await response.json()
        except aiohttp.ClientError as e:
            logger.error(f"Async API request failed: {method} {url} - {e}")
            raise RuntimeError(f"API request failed: {e}")
    
    # --- Expenses ---
    
    async def add_expense(self, category: str, amount: float) -> Tuple[bool, float]:
        """Add expense. Returns (exceeded_limit, remaining_amount)"""
        data = await self._request("POST", "/expenses", json={
            "category": category,
            "amount": amount
        })
        return data["exceeded"], data["remaining"]
    
    async def get_expenses_for_month(self, month: str) -> List[Dict[str, Any]]:
        """Get expenses for a specific month."""
        return await self._request("GET", "/expenses", params={"month": month})
    
    # --- Reports ---
    
    async def get_month_report(self, month: str) -> Dict[str, Any]:
        """Get spending report for a month."""
        return await self._request("GET", "/report", params={"month": month})
    
    async def get_remaining(self, month: str) -> Dict[str, float]:
        """Get remaining budget for each category."""
        data = await self._request("GET", "/report", params={"month": month})
        return data["report"]
    
    # --- Limits ---
    
    async def list_limits(self) -> List[Dict[str, Any]]:
        """Get all category limits."""
        return await self._request("GET", "/limits")
    
    async def set_limit(self, category: str, amount: float) -> None:
        """Set category limit."""
        await self._request("POST", "/limits", json={
            "category": category,
            "amount": amount
        })
    
    # --- Utility ---
    
    def get_current_month(self) -> str:
        """Get current month in YYYY-MM format."""
        return datetime.now().strftime("%Y-%m")


# Global instances
api_client = BudgetApiClient()
async_api_client = AsyncBudgetApiClient()
