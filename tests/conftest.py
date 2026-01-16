"""
Pytest configuration and fixtures.
"""
import os
import pytest
import asyncio
from typing import AsyncGenerator
import asyncpg
from decimal import Decimal

# Test database configuration
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/budget_pet_test")


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    """Create database connection pool for tests."""
    pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=5)
    yield pool
    await pool.close()


@pytest.fixture(scope="function")
async def clean_db(db_pool: asyncpg.Pool):
    """Clean database before each test."""
    async with db_pool.acquire() as conn:
        # Truncate all tables
        tables = [
            "finance_payments",
            "finance_income",
            "finance_loans",
            "finance_credit_cards",
            "expenses",
            "monthly_budgets",
            "category_limits",
            "settings",
            "peers",
            "budget_alerts"
        ]
        for table in tables:
            await conn.execute(f"TRUNCATE TABLE {table} CASCADE")
    yield
    # Cleanup after test
    async with db_pool.acquire() as conn:
        for table in tables:
            await conn.execute(f"TRUNCATE TABLE {table} CASCADE")


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
