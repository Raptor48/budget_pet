"""
Tests for finance repository (loans, cards, payments, income).
"""
import pytest
import asyncio
from decimal import Decimal
from datetime import date
from web.finance.repo import FinanceRepository
from web.finance.models import (
    LoanCreate, LoanUpdate,
    CreditCardCreate, CreditCardUpdate,
    PaymentCreate,
    IncomeCreate
)


# Test database URL
TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/budget_pet_test"


@pytest.fixture
async def repo():
    """Create repository instance for testing."""
    repo = FinanceRepository(TEST_DATABASE_URL)
    await repo.init_tables()
    yield repo
    await repo.close()


@pytest.fixture
async def clean_repo(repo):
    """Clean repository before each test."""
    pool = await repo.get_pool()
    async with pool.acquire() as conn:
        tables = [
            "finance_payments",
            "finance_income",
            "finance_loans",
            "finance_credit_cards"
        ]
        for table in tables:
            await conn.execute(f"TRUNCATE TABLE {table} CASCADE")
    yield repo


class TestLoans:
    """Tests for loan operations."""
    
    @pytest.mark.asyncio
    async def test_create_loan(self, clean_repo):
        """Test creating a loan."""
        loan_data = LoanCreate(
            name="Test Car Loan",
            category_name="Auto Loan",
            apr_percent=Decimal("5.5"),
            current_balance_cents=2500000,  # $25,000
            due_day=15,
            min_payment_cents=50000,  # $500
            remaining_months=36,
            is_active=True
        )
        
        loan = await clean_repo.create_loan(loan_data)
        
        assert loan.id is not None
        assert loan.name == "Test Car Loan"
        assert loan.apr_percent == Decimal("5.5")
        assert loan.current_balance_cents == 2500000
        assert loan.min_payment_cents == 50000
        assert loan.is_active is True
    
    @pytest.mark.asyncio
    async def test_get_loans(self, clean_repo):
        """Test getting all loans."""
        # Create multiple loans
        loan1 = await clean_repo.create_loan(LoanCreate(
            name="Loan 1",
            category_name="Auto",
            apr_percent=Decimal("5.5"),
            current_balance_cents=2500000,
            due_day=15,
            min_payment_cents=50000,
            remaining_months=36,
            is_active=True
        ))
        
        loan2 = await clean_repo.create_loan(LoanCreate(
            name="Loan 2",
            category_name="Personal",
            apr_percent=Decimal("7.0"),
            current_balance_cents=1000000,
            due_day=20,
            min_payment_cents=20000,
            remaining_months=24,
            is_active=True
        ))
        
        # Get all active loans
        loans = await clean_repo.get_loans(active_only=True)
        
        assert len(loans) == 2
        assert any(l.id == loan1.id for l in loans)
        assert any(l.id == loan2.id for l in loans)
    
    @pytest.mark.asyncio
    async def test_update_loan(self, clean_repo):
        """Test updating a loan."""
        # Create loan
        loan = await clean_repo.create_loan(LoanCreate(
            name="Test Loan",
            category_name="Auto",
            apr_percent=Decimal("5.5"),
            current_balance_cents=2500000,
            due_day=15,
            min_payment_cents=50000,
            remaining_months=36,
            is_active=True
        ))
        
        # Update loan
        update_data = LoanUpdate(
            current_balance_cents=2000000,  # Reduced balance
            min_payment_cents=60000  # Increased payment
        )
        
        updated = await clean_repo.update_loan(loan.id, update_data)
        
        assert updated.current_balance_cents == 2000000
        assert updated.min_payment_cents == 60000
        assert updated.name == "Test Loan"  # Unchanged
    
    @pytest.mark.asyncio
    async def test_delete_loan(self, clean_repo):
        """Test soft deleting a loan."""
        # Create loan
        loan = await clean_repo.create_loan(LoanCreate(
            name="Test Loan",
            category_name="Auto",
            apr_percent=Decimal("5.5"),
            current_balance_cents=2500000,
            due_day=15,
            min_payment_cents=50000,
            remaining_months=36,
            is_active=True
        ))
        
        # Delete loan (soft delete)
        success = await clean_repo.delete_loan(loan.id)
        assert success is True
        
        # Loan should not appear in active loans
        loans = await clean_repo.get_loans(active_only=True)
        assert not any(l.id == loan.id for l in loans)
        
        # But should appear in all loans
        all_loans = await clean_repo.get_loans(active_only=False)
        assert any(l.id == loan.id for l in all_loans)


class TestCreditCards:
    """Tests for credit card operations."""
    
    @pytest.mark.asyncio
    async def test_create_card(self, clean_repo):
        """Test creating a credit card."""
        card_data = CreditCardCreate(
            name="Test Credit Card",
            category_name="Chase Freedom",
            apr_percent=Decimal("24.99"),
            current_balance_cents=150000,  # $1,500
            credit_limit_cents=500000,  # $5,000
            due_day=20,
            min_payment_cents=2500,  # $25
            is_active=True
        )
        
        card = await clean_repo.create_card(card_data)
        
        assert card.id is not None
        assert card.name == "Test Credit Card"
        assert card.apr_percent == Decimal("24.99")
        assert card.current_balance_cents == 150000
        assert card.credit_limit_cents == 500000
        assert card.is_active is True
    
    @pytest.mark.asyncio
    async def test_update_card(self, clean_repo):
        """Test updating a credit card."""
        # Create card
        card = await clean_repo.create_card(CreditCardCreate(
            name="Test Card",
            category_name="Chase",
            apr_percent=Decimal("24.99"),
            current_balance_cents=150000,
            credit_limit_cents=500000,
            due_day=20,
            min_payment_cents=2500,
            is_active=True
        ))
        
        # Update card
        update_data = CreditCardUpdate(
            current_balance_cents=200000,  # Increased balance
            credit_limit_cents=600000  # Increased limit
        )
        
        updated = await clean_repo.update_card(card.id, update_data)
        
        assert updated.current_balance_cents == 200000
        assert updated.credit_limit_cents == 600000


class TestPayments:
    """Tests for payment operations."""
    
    @pytest.mark.asyncio
    async def test_create_payment_for_loan(self, clean_repo):
        """Test creating a payment for a loan."""
        # Create loan
        loan = await clean_repo.create_loan(LoanCreate(
            name="Test Loan",
            category_name="Auto",
            apr_percent=Decimal("5.5"),
            current_balance_cents=2500000,
            due_day=15,
            min_payment_cents=50000,
            remaining_months=36,
            is_active=True
        ))
        
        # Create payment
        payment_data = PaymentCreate(
            account_type="loan",
            account_id=loan.id,
            amount_cents=100000,  # $1,000
            occurred_at=date(2025, 1, 15),
            person="Denis",
            note="Extra payment"
        )
        
        payment = await clean_repo.create_payment(payment_data)
        
        assert payment.id is not None
        assert payment.account_type == "loan"
        assert payment.account_id == loan.id
        assert payment.amount_cents == 100000
        
        # Check that loan balance was updated
        updated_loan = await clean_repo.get_loan(loan.id)
        assert updated_loan.current_balance_cents == 2400000  # 25,000 - 1,000
    
    @pytest.mark.asyncio
    async def test_create_payment_for_card(self, clean_repo):
        """Test creating a payment for a credit card."""
        # Create card
        card = await clean_repo.create_card(CreditCardCreate(
            name="Test Card",
            category_name="Chase",
            apr_percent=Decimal("24.99"),
            current_balance_cents=150000,
            credit_limit_cents=500000,
            due_day=20,
            min_payment_cents=2500,
            is_active=True
        ))
        
        # Create payment
        payment_data = PaymentCreate(
            account_type="card",
            account_id=card.id,
            amount_cents=50000,  # $500
            occurred_at=date(2025, 1, 20),
            person="Denis",
            note="Monthly payment"
        )
        
        payment = await clean_repo.create_payment(payment_data)
        
        assert payment.account_type == "card"
        assert payment.account_id == card.id
        
        # Check that card balance was updated
        updated_card = await clean_repo.get_card(card.id)
        assert updated_card.current_balance_cents == 100000  # 1,500 - 500
    
    @pytest.mark.asyncio
    async def test_payment_prevents_negative_balance(self, clean_repo):
        """Test that payment doesn't make balance negative."""
        # Create loan with small balance
        loan = await clean_repo.create_loan(LoanCreate(
            name="Test Loan",
            category_name="Auto",
            apr_percent=Decimal("5.5"),
            current_balance_cents=50000,  # $500
            due_day=15,
            min_payment_cents=50000,
            remaining_months=1,
            is_active=True
        ))
        
        # Try to pay more than balance
        payment_data = PaymentCreate(
            account_type="loan",
            account_id=loan.id,
            amount_cents=100000,  # $1,000 (more than balance)
            occurred_at=date(2025, 1, 15),
            person="Denis",
            note="Overpayment"
        )
        
        payment = await clean_repo.create_payment(payment_data)
        
        # Balance should be 0, not negative
        updated_loan = await clean_repo.get_loan(loan.id)
        assert updated_loan.current_balance_cents == 0


class TestIncome:
    """Tests for income operations."""
    
    @pytest.mark.asyncio
    async def test_create_income(self, clean_repo):
        """Test creating income entry."""
        income_data = IncomeCreate(
            person="Denis",
            amount_cents=500000,  # $5,000
            occurred_at=date(2025, 1, 15),
            note="Salary"
        )
        
        income = await clean_repo.create_income(income_data)
        
        assert income.id is not None
        assert income.person == "Denis"
        assert income.amount_cents == 500000
        assert income.occurred_at == date(2025, 1, 15)
    
    @pytest.mark.asyncio
    async def test_get_income_by_month(self, clean_repo):
        """Test getting income filtered by month."""
        # Create income for different months
        await clean_repo.create_income(IncomeCreate(
            person="Denis",
            amount_cents=500000,
            occurred_at=date(2025, 1, 15),
            note="January salary"
        ))
        
        await clean_repo.create_income(IncomeCreate(
            person="Taya",
            amount_cents=400000,
            occurred_at=date(2025, 1, 20),
            note="January salary"
        ))
        
        await clean_repo.create_income(IncomeCreate(
            person="Denis",
            amount_cents=500000,
            occurred_at=date(2025, 2, 15),
            note="February salary"
        ))
        
        # Get income for January
        jan_income = await clean_repo.get_income(month="2025-01")
        
        assert len(jan_income) == 2
        assert sum(i.amount_cents for i in jan_income) == 900000  # 5,000 + 4,000
    
    @pytest.mark.asyncio
    async def test_get_income_by_person(self, clean_repo):
        """Test getting income filtered by person."""
        # Create income for different people
        await clean_repo.create_income(IncomeCreate(
            person="Denis",
            amount_cents=500000,
            occurred_at=date(2025, 1, 15),
            note="Salary"
        ))
        
        await clean_repo.create_income(IncomeCreate(
            person="Taya",
            amount_cents=400000,
            occurred_at=date(2025, 1, 20),
            note="Salary"
        ))
        
        # Get income for Denis
        denis_income = await clean_repo.get_income(person="Denis")
        
        assert len(denis_income) == 1
        assert denis_income[0].person == "Denis"
        assert denis_income[0].amount_cents == 500000


class TestSummary:
    """Tests for financial summary."""
    
    @pytest.mark.asyncio
    async def test_get_summary(self, clean_repo):
        """Test getting financial summary."""
        # Create loan
        loan = await clean_repo.create_loan(LoanCreate(
            name="Test Loan",
            category_name="Auto",
            apr_percent=Decimal("5.5"),
            current_balance_cents=2500000,
            due_day=15,
            min_payment_cents=50000,
            remaining_months=36,
            is_active=True
        ))
        
        # Create card
        card = await clean_repo.create_card(CreditCardCreate(
            name="Test Card",
            category_name="Chase",
            apr_percent=Decimal("24.99"),
            current_balance_cents=150000,
            credit_limit_cents=500000,
            due_day=20,
            min_payment_cents=2500,
            is_active=True
        ))
        
        # Create income
        await clean_repo.create_income(IncomeCreate(
            person="Denis",
            amount_cents=500000,
            occurred_at=date(2025, 1, 15),
            note="Salary"
        ))
        
        await clean_repo.create_income(IncomeCreate(
            person="Taya",
            amount_cents=400000,
            occurred_at=date(2025, 1, 20),
            note="Salary"
        ))
        
        # Get summary
        summary = await clean_repo.get_summary("2025-01")
        
        assert summary.income_total_cents == 900000  # 5,000 + 4,000
        assert summary.debt_totals.combined_balance_cents == 2650000  # 25,000 + 1,500
        assert summary.debt_totals.min_payments_cents == 52500  # 500 + 25
