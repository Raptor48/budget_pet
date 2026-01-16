"""
Tests for FastAPI endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from web.main import app
import os

# Mock database URL for testing
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/budget_pet_test")


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHealthCheck:
    """Tests for health check endpoint."""
    
    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


class TestExpenses:
    """Tests for expense endpoints."""
    
    def test_get_expenses_empty(self, client):
        """Test getting expenses when none exist."""
        response = client.get("/expenses?month=2025-01")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0
    
    def test_create_expense(self, client):
        """Test creating an expense."""
        expense_data = {
            "category": "Food",
            "amount": 50.0
        }
        
        response = client.post("/expenses", json=expense_data)
        assert response.status_code == 200
        data = response.json()
        assert "exceeded" in data
        assert "remaining" in data
    
    def test_get_expenses_with_data(self, client):
        """Test getting expenses after creating some."""
        # Create expense
        client.post("/expenses", json={"category": "Food", "amount": 50.0})
        
        # Get expenses
        response = client.get("/expenses?month=2025-01")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert any(e["category"] == "Food" for e in data)


class TestLimits:
    """Tests for limit endpoints."""
    
    def test_get_limits_empty(self, client):
        """Test getting limits when none exist."""
        response = client.get("/limits")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_create_limit(self, client):
        """Test creating a limit."""
        limit_data = {
            "category": "Food",
            "default_limit": 1000.0
        }
        
        response = client.post("/limits", json=limit_data)
        assert response.status_code == 200
        data = response.json()
        assert data["category"] == "Food"
        assert data["default_limit"] == 1000.0
    
    def test_get_limits_with_data(self, client):
        """Test getting limits after creating some."""
        # Create limit
        client.post("/limits", json={"category": "Food", "default_limit": 1000.0})
        
        # Get limits
        response = client.get("/limits")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert any(l["category"] == "Food" for l in data)


class TestReports:
    """Tests for report endpoints."""
    
    def test_get_report_empty(self, client):
        """Test getting report when no data exists."""
        response = client.get("/report?month=2025-01")
        assert response.status_code == 200
        data = response.json()
        assert "report" in data
        assert isinstance(data["report"], dict)
    
    def test_get_report_with_data(self, client):
        """Test getting report with expenses."""
        # Create limit and expense
        client.post("/limits", json={"category": "Food", "default_limit": 1000.0})
        client.post("/expenses", json={"category": "Food", "amount": 200.0})
        
        # Get report
        response = client.get("/report?month=2025-01")
        assert response.status_code == 200
        data = response.json()
        assert "Food" in data["report"]
        assert data["report"]["Food"]["spent"] == 200.0
        assert data["report"]["Food"]["budget"] == 1000.0
        assert data["report"]["Food"]["remaining"] == 800.0
    
    def test_get_report_with_comparison(self, client):
        """Test getting report with month comparison."""
        # Create data for two months
        client.post("/limits", json={"category": "Food", "default_limit": 1000.0})
        client.post("/expenses", json={"category": "Food", "amount": 200.0, "date": "2025-01-15"})
        client.post("/expenses", json={"category": "Food", "amount": 300.0, "date": "2025-02-10"})
        
        # Get report with comparison
        response = client.get("/report?month=2025-02&compare=2025-01")
        assert response.status_code == 200
        data = response.json()
        assert "report" in data
        assert "comparison" in data
        assert "Food" in data["comparison"]
        # February spent 300, January spent 200, so 50% increase
        assert data["comparison"]["Food"] == pytest.approx(50.0, rel=1e-6)


class TestFinanceEndpoints:
    """Tests for finance module endpoints."""
    
    def test_get_loans_empty(self, client):
        """Test getting loans when none exist."""
        response = client.get("/api/finances/loans")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0
    
    def test_create_loan(self, client):
        """Test creating a loan."""
        loan_data = {
            "name": "Test Loan",
            "category_name": "Auto",
            "apr_percent": 5.5,
            "current_balance_cents": 2500000,
            "due_day": 15,
            "min_payment_cents": 50000,
            "remaining_months": 36,
            "is_active": True
        }
        
        response = client.post("/api/finances/loans", json=loan_data)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Loan"
        assert data["current_balance_cents"] == 2500000
    
    def test_get_summary(self, client):
        """Test getting financial summary."""
        # Create loan and income
        client.post("/api/finances/loans", json={
            "name": "Test Loan",
            "category_name": "Auto",
            "apr_percent": 5.5,
            "current_balance_cents": 2500000,
            "due_day": 15,
            "min_payment_cents": 50000,
            "remaining_months": 36,
            "is_active": True
        })
        
        client.post("/api/finances/income", json={
            "person": "Denis",
            "amount_cents": 500000,
            "occurred_at": "2025-01-15",
            "note": "Salary"
        })
        
        # Get summary
        response = client.get("/api/finances/summary?month=2025-01")
        assert response.status_code == 200
        data = response.json()
        assert "income_total_cents" in data
        assert "debt_totals" in data
