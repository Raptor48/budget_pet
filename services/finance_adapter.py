"""
Finance API adapter for bot integration.
"""

import os
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime

# API base URL
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

class FinanceAPIError(Exception):
    """Finance API error."""
    pass

def _make_request(method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
    """Make API request."""
    url = f"{API_BASE_URL}{endpoint}"
    
    try:
        response = requests.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise FinanceAPIError(f"API request failed: {e}")

def get_finance_accounts() -> Dict[str, List[Dict[str, Any]]]:
    """Get all finance accounts (loans and credit cards)."""
    return _make_request("GET", "/api/finances/accounts")

def get_finance_summary(month: str) -> Dict[str, Any]:
    """Get finance summary for a month."""
    return _make_request("GET", f"/api/finances/summary?month={month}")

def create_finance_payment(account_type: str, account_id: int, amount: float, 
                          occurred_at: str, person: Optional[str] = None, 
                          note: Optional[str] = None) -> Dict[str, Any]:
    """Create a finance payment."""
    data = {
        "account_type": account_type,
        "account_id": account_id,
        "amount_cents": int(amount * 100),  # Convert to cents
        "occurred_at": occurred_at,
        "person": person,
        "note": note
    }
    return _make_request("POST", "/api/finances/payments", json=data)

def get_loans() -> List[Dict[str, Any]]:
    """Get all loans."""
    return _make_request("GET", "/api/finances/loans")

def get_cards() -> List[Dict[str, Any]]:
    """Get all credit cards."""
    return _make_request("GET", "/api/finances/cards")

def get_income(month: str, person: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get income entries for a month."""
    params = {"month": month}
    if person:
        params["person"] = person
    return _make_request("GET", "/api/finances/income", params=params)
