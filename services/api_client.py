"""
Async API client for communicating with FastAPI backend (used by Telegram bot).
"""
import aiohttp
from typing import List, Dict, Optional, Any
from datetime import datetime
import os
import logging

logger = logging.getLogger("budget-api-client")
logger.setLevel(logging.INFO)


class AsyncBudgetApiClient:
    """Asynchronous API client for Telegram Bot."""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("API_BASE_URL", "https://fastapi-production-eadf.up.railway.app")
        
    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make async HTTP request with error handling."""
        url = f"{self.base_url}{endpoint}"
        timeout = aiohttp.ClientTimeout(total=30)
        
        try:
            logger.info(f"Making async API request: {method} {url}")
            # Create SSL context that doesn't verify certificates for Railway.app
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.request(method, url, **kwargs) as response:
                    response.raise_for_status()
                    result = await response.json()
                    logger.info(f"Async API request successful: {method} {url} - Status: {response.status}")
                    return result
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
    
    # --- Limits ---
    
    async def list_limits(self) -> List[Dict[str, Any]]:
        """Get all category limits."""
        return await self._request("GET", "/limits")
    
    async def set_limit(self, category: str, amount: float) -> None:
        """Set category limit."""
        await self._request("POST", "/limits", json={
            "category": category,
            "default_limit": amount
        })
    
    # --- Notifications ---
    
    async def add_peer(self, user_id: int, username: str) -> None:
        """Add a peer for notifications."""
        await self._request("POST", "/api/finances/peers", params={
            "user_id": user_id,
            "username": username
        })
    
    async def get_peers(self, exclude_id: Optional[int] = None) -> Dict[str, List[int]]:
        """Get peer IDs for notifications."""
        params = {}
        if exclude_id is not None:
            params["exclude_id"] = exclude_id
        return await self._request("GET", "/api/finances/peers", params=params)
    
    async def check_alert(self, category: str, month: str, threshold: int) -> Dict[str, bool]:
        """Check if threshold alert was already sent."""
        return await self._request("GET", "/api/finances/alerts/check", params={
            "category": category,
            "month": month,
            "threshold": threshold
        })
    
    async def mark_alert(self, category: str, month: str, threshold: int) -> None:
        """Mark threshold alert as sent."""
        await self._request("POST", "/api/finances/alerts/mark", params={
            "category": category,
            "month": month,
            "threshold": threshold
        })

    # --- Utility ---
    
    def get_current_month(self) -> str:
        """Get current month in YYYY-MM format."""
        return datetime.now().strftime("%Y-%m")
