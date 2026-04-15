"""
Finance API adapter for bot integration.
"""

import os
import logging
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# Cached session token (obtained via lazy login)
_session_token: Optional[str] = None


class FinanceAPIError(Exception):
    """Finance API error."""
    pass


def _login() -> str:
    """Login to API and return session token."""
    url = f"{API_BASE_URL}/api/auth/login"
    login = os.getenv("ADMIN_LOGIN", "admin")
    password = os.getenv("ADMIN_PASSWORD")

    if not password:
        raise FinanceAPIError("ADMIN_PASSWORD not set — cannot authenticate finance adapter")

    try:
        response = requests.post(url, json={"username": login, "password": password}, timeout=15)
        response.raise_for_status()
        data = response.json()
        token = data.get("token")
        if not token:
            raise FinanceAPIError("Login response did not contain a token")
        logger.info("Finance adapter: login successful")
        return token
    except requests.exceptions.RequestException as e:
        raise FinanceAPIError(f"Finance adapter login failed: {e}")


def _get_token() -> str:
    """Return cached token, logging in if necessary."""
    global _session_token
    if not _session_token:
        _session_token = _login()
    return _session_token


def _make_request(method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
    """Make authenticated API request. Re-authenticates on 401."""
    global _session_token

    url = f"{API_BASE_URL}{endpoint}"
    token = _get_token()

    try:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        response = requests.request(method, url, headers=headers, **kwargs)

        if response.status_code == 401:
            # Token expired or invalidated — re-login once
            logger.warning("Finance adapter: 401 received, re-authenticating")
            _session_token = None
            token = _get_token()
            headers["Authorization"] = f"Bearer {token}"
            response = requests.request(method, url, headers=headers, **kwargs)

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
        "amount_cents": int(amount * 100),
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
    params: Dict[str, Any] = {"month": month}
    if person:
        params["person"] = person
    return _make_request("GET", "/api/finances/income", params=params)
