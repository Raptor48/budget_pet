"""
Pytest configuration and fixtures.
"""
import pytest
from decimal import Decimal


@pytest.fixture
def sample_loan_data():
    """Sample loan data for testing."""
    return {
        "name": "Test Car Loan",
        "category_name": "Auto Loan",
        "apr_percent": Decimal("5.5"),
        "current_balance_cents": 2500000,  # $25,000
        "due_day": 15,
        "min_payment_cents": 50000,  # $500
        "remaining_months": 36,
        "is_active": True
    }


@pytest.fixture
def sample_card_data():
    """Sample credit card data for testing."""
    return {
        "name": "Test Credit Card",
        "category_name": "Chase Freedom",
        "apr_percent": Decimal("24.99"),
        "current_balance_cents": 150000,  # $1,500
        "credit_limit_cents": 500000,  # $5,000
        "due_day": 20,
        "min_payment_cents": 2500,  # $25
        "is_active": True
    }
