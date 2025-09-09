#!/usr/bin/env python3
"""
Test script for finance module locally.
"""

import asyncio
import os
from web.finance.repo import FinanceRepository
from web.finance.models import LoanCreate, CreditCardCreate, IncomeCreate, PaymentCreate

async def test_finance():
    """Test finance module functionality."""
    
    # Set up database URL for local testing
    database_url = os.getenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/budget_pet")
    
    print(f"Testing with DATABASE_URL: {database_url}")
    
    # Create repository
    repo = FinanceRepository(database_url)
    
    try:
        # Initialize tables
        print("Initializing tables...")
        await repo.init_tables()
        print("✓ Tables initialized")
        
        # Test loan creation
        print("\nTesting loan creation...")
        loan = LoanCreate(
            name="Test Car Loan",
            category_name="Auto Loan",
            apr_percent=5.5,
            current_balance_cents=2500000,  # $25,000
            due_day=15,
            min_payment_cents=50000,  # $500
            remaining_months=36,
            is_active=True
        )
        created_loan = await repo.create_loan(loan)
        print(f"✓ Created loan: {created_loan.name} (ID: {created_loan.id})")
        
        # Test credit card creation
        print("\nTesting credit card creation...")
        card = CreditCardCreate(
            name="Test Credit Card",
            category_name="Chase Freedom",
            apr_percent=24.99,
            current_balance_cents=150000,  # $1,500
            credit_limit_cents=500000,  # $5,000
            due_day=20,
            min_payment_cents=2500,  # $25
            is_active=True
        )
        created_card = await repo.create_card(card)
        print(f"✓ Created card: {created_card.name} (ID: {created_card.id})")
        
        # Test income creation
        print("\nTesting income creation...")
        income = IncomeCreate(
            person="Denis",
            amount_cents=500000,  # $5,000
            occurred_at="2025-09-15",
            note="Test salary"
        )
        created_income = await repo.create_income(income)
        print(f"✓ Created income: {created_income.person} - ${created_income.amount_cents/100}")
        
        # Test payment creation
        print("\nTesting payment creation...")
        payment = PaymentCreate(
            account_type="loan",
            account_id=created_loan.id,
            amount_cents=100000,  # $1,000
            occurred_at="2025-09-15",
            person="Denis",
            note="Test payment"
        )
        created_payment = await repo.create_payment(payment)
        print(f"✓ Created payment: ${created_payment.amount_cents/100} for {created_payment.account_type}")
        
        # Test summary
        print("\nTesting summary...")
        summary = await repo.get_summary("2025-09")
        print(f"✓ Summary for 2025-09:")
        print(f"  - Income total: ${summary.income_total_cents/100}")
        print(f"  - Debt total: ${summary.debt_totals.combined_balance_cents/100}")
        print(f"  - Min payments: ${summary.debt_totals.min_payments_cents/100}")
        
        # Test accounts for bot
        print("\nTesting accounts for bot...")
        accounts = await repo.get_accounts()
        print(f"✓ Found {len(accounts.loans)} loans and {len(accounts.cards)} cards")
        
        print("\n✅ All tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Close repository
        await repo.close()

if __name__ == "__main__":
    asyncio.run(test_finance())
