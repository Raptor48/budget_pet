"""
API routes for finance module.
"""

from datetime import date
from typing import List, Optional, Literal
from fastapi import APIRouter, HTTPException, Query
from .models import (
    LoanCreate, LoanUpdate, LoanOut,
    CreditCardCreate, CreditCardUpdate, CreditCardOut,
    PaymentCreate, PaymentOut,
    IncomeCreate, IncomeUpdate, IncomeOut,
    RecurringExpenseCreate, RecurringExpenseUpdate, RecurringExpenseOut,
    PiggyBankCreate, PiggyBankUpdate, PiggyBankOut,
    SummaryOut, AccountsOut, InterestSummary, AccountAnalytics, PaymentAnalytics
)
from .repo import get_finance_repo

router = APIRouter(prefix="/api/finances", tags=["finances"])


# Loans endpoints
@router.get("/loans", response_model=List[LoanOut])
async def get_loans(active_only: bool = Query(True, description="Filter by active status")):
    """Get all loans."""
    repo = get_finance_repo()
    return await repo.get_loans(active_only=active_only)


@router.post("/loans", response_model=LoanOut)
async def create_loan(loan: LoanCreate):
    """Create a new loan."""
    repo = get_finance_repo()
    return await repo.create_loan(loan)


@router.get("/loans/{loan_id}", response_model=LoanOut)
async def get_loan(loan_id: int):
    """Get a loan by ID."""
    repo = get_finance_repo()
    loan = await repo.get_loan(loan_id)
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    return loan


@router.patch("/loans/{loan_id}", response_model=LoanOut)
async def update_loan(loan_id: int, loan: LoanUpdate):
    """Update a loan."""
    repo = get_finance_repo()
    updated_loan = await repo.update_loan(loan_id, loan)
    if not updated_loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    return updated_loan


@router.delete("/loans/{loan_id}")
async def delete_loan(loan_id: int):
    """Soft delete a loan."""
    repo = get_finance_repo()
    success = await repo.delete_loan(loan_id)
    if not success:
        raise HTTPException(status_code=404, detail="Loan not found")
    return {"message": "Loan deleted successfully"}


# Credit Cards endpoints
@router.get("/cards", response_model=List[CreditCardOut])
async def get_cards(active_only: bool = Query(True, description="Filter by active status")):
    """Get all credit cards."""
    repo = get_finance_repo()
    return await repo.get_cards(active_only=active_only)


@router.post("/cards", response_model=CreditCardOut)
async def create_card(card: CreditCardCreate):
    """Create a new credit card."""
    repo = get_finance_repo()
    return await repo.create_card(card)


@router.get("/cards/{card_id}", response_model=CreditCardOut)
async def get_card(card_id: int):
    """Get a credit card by ID."""
    repo = get_finance_repo()
    card = await repo.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Credit card not found")
    return card


@router.patch("/cards/{card_id}", response_model=CreditCardOut)
async def update_card(card_id: int, card: CreditCardUpdate):
    """Update a credit card."""
    repo = get_finance_repo()
    updated_card = await repo.update_card(card_id, card)
    if not updated_card:
        raise HTTPException(status_code=404, detail="Credit card not found")
    return updated_card


@router.delete("/cards/{card_id}")
async def delete_card(card_id: int):
    """Soft delete a credit card."""
    repo = get_finance_repo()
    success = await repo.delete_card(card_id)
    if not success:
        raise HTTPException(status_code=404, detail="Credit card not found")
    return {"message": "Credit card deleted successfully"}


# Payments endpoints
@router.post("/payments", response_model=PaymentOut)
async def create_payment(payment: PaymentCreate):
    """Create a payment and update account balance."""
    repo = get_finance_repo()
    return await repo.create_payment(payment)


@router.get("/payments", response_model=List[PaymentOut])
async def get_payments(
    account_type: Optional[Literal["loan", "card"]] = Query(None, description="Filter by account type"),
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    start_date: Optional[date] = Query(None, description="Filter by start date"),
    end_date: Optional[date] = Query(None, description="Filter by end date")
):
    """Get payments with optional filters."""
    repo = get_finance_repo()
    return await repo.get_payments(account_type, account_id, start_date, end_date)


# Income endpoints
@router.get("/income", response_model=List[IncomeOut])
async def get_income(
    month: Optional[str] = Query(None, description="Filter by month (YYYY-MM)"),
    person: Optional[Literal["Denis", "Taya"]] = Query(None, description="Filter by person")
):
    """Get income entries with optional filters."""
    repo = get_finance_repo()
    return await repo.get_income(month, person)


@router.post("/income", response_model=IncomeOut)
async def create_income(income: IncomeCreate):
    """Create a new income entry."""
    repo = get_finance_repo()
    return await repo.create_income(income)


@router.get("/income/{income_id}", response_model=IncomeOut)
async def get_income_by_id(income_id: int):
    """Get income entry by ID."""
    repo = get_finance_repo()
    income = await repo.get_income_by_id(income_id)
    if not income:
        raise HTTPException(status_code=404, detail="Income entry not found")
    return income


@router.patch("/income/{income_id}", response_model=IncomeOut)
async def update_income(income_id: int, income: IncomeUpdate):
    """Update an income entry."""
    repo = get_finance_repo()
    updated_income = await repo.update_income(income_id, income)
    if not updated_income:
        raise HTTPException(status_code=404, detail="Income entry not found")
    return updated_income


@router.delete("/income/{income_id}")
async def delete_income(income_id: int):
    """Delete an income entry."""
    repo = get_finance_repo()
    success = await repo.delete_income(income_id)
    if not success:
        raise HTTPException(status_code=404, detail="Income entry not found")
    return {"message": "Income entry deleted successfully"}


# Recurring Expenses endpoints
@router.get("/recurring-expenses", response_model=List[RecurringExpenseOut])
async def get_recurring_expenses(active_only: bool = Query(True, description="Filter by active status")):
    """Get all recurring expenses."""
    repo = get_finance_repo()
    return await repo.get_recurring_expenses(active_only=active_only)


@router.post("/recurring-expenses", response_model=RecurringExpenseOut)
async def create_recurring_expense(expense: RecurringExpenseCreate):
    """Create a new recurring expense."""
    repo = get_finance_repo()
    return await repo.create_recurring_expense(expense)


@router.get("/recurring-expenses/{expense_id}", response_model=RecurringExpenseOut)
async def get_recurring_expense(expense_id: int):
    """Get a recurring expense by ID."""
    repo = get_finance_repo()
    expense = await repo.get_recurring_expense_by_id(expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Recurring expense not found")
    return expense


@router.patch("/recurring-expenses/{expense_id}", response_model=RecurringExpenseOut)
async def update_recurring_expense(expense_id: int, expense: RecurringExpenseUpdate):
    """Update a recurring expense."""
    repo = get_finance_repo()
    updated_expense = await repo.update_recurring_expense(expense_id, expense)
    if not updated_expense:
        raise HTTPException(status_code=404, detail="Recurring expense not found")
    return updated_expense


@router.delete("/recurring-expenses/{expense_id}")
async def delete_recurring_expense(expense_id: int):
    """Delete a recurring expense."""
    repo = get_finance_repo()
    success = await repo.delete_recurring_expense(expense_id)
    if not success:
        raise HTTPException(status_code=404, detail="Recurring expense not found")
    return {"message": "Recurring expense deleted successfully"}


# Piggy Banks endpoints
@router.get("/piggy-banks", response_model=List[PiggyBankOut])
async def get_piggy_banks(active_only: bool = Query(True, description="Filter by active status")):
    """Get all piggy banks."""
    repo = get_finance_repo()
    return await repo.get_piggy_banks(active_only=active_only)


@router.post("/piggy-banks", response_model=PiggyBankOut)
async def create_piggy_bank(piggy: PiggyBankCreate):
    """Create a new piggy bank."""
    repo = get_finance_repo()
    return await repo.create_piggy_bank(piggy)


@router.get("/piggy-banks/{piggy_id}", response_model=PiggyBankOut)
async def get_piggy_bank(piggy_id: int):
    """Get a piggy bank by ID."""
    repo = get_finance_repo()
    piggy = await repo.get_piggy_bank_by_id(piggy_id)
    if not piggy:
        raise HTTPException(status_code=404, detail="Piggy bank not found")
    return piggy


@router.patch("/piggy-banks/{piggy_id}", response_model=PiggyBankOut)
async def update_piggy_bank(piggy_id: int, piggy: PiggyBankUpdate):
    """Update a piggy bank."""
    repo = get_finance_repo()
    updated_piggy = await repo.update_piggy_bank(piggy_id, piggy)
    if not updated_piggy:
        raise HTTPException(status_code=404, detail="Piggy bank not found")
    return updated_piggy


@router.delete("/piggy-banks/{piggy_id}")
async def delete_piggy_bank(piggy_id: int):
    """Delete a piggy bank."""
    repo = get_finance_repo()
    success = await repo.delete_piggy_bank(piggy_id)
    if not success:
        raise HTTPException(status_code=404, detail="Piggy bank not found")
    return {"message": "Piggy bank deleted successfully"}


@router.post("/piggy-banks/{piggy_id}/add-amount", response_model=PiggyBankOut)
async def add_to_piggy_bank(piggy_id: int, amount_cents: int = Query(..., ge=1, description="Amount to add in cents")):
    """Add amount to piggy bank's current_amount_cents."""
    repo = get_finance_repo()
    updated_piggy = await repo.add_to_piggy_bank(piggy_id, amount_cents)
    if not updated_piggy:
        raise HTTPException(status_code=404, detail="Piggy bank not found")
    return updated_piggy


# Summary endpoint
@router.get("/summary", response_model=SummaryOut)
async def get_summary(month: str = Query(..., description="Month in YYYY-MM format")):
    """Get financial summary for a month."""
    repo = get_finance_repo()
    return await repo.get_summary(month)


# Analytics endpoints
@router.get("/analytics/interest-summary", response_model=InterestSummary)
async def get_interest_summary(month: str = Query(..., description="Month in YYYY-MM format")):
    """Get comprehensive interest and analytics summary for a month."""
    try:
        # Validate month format
        year, month_num = map(int, month.split('-'))
        if not (1 <= month_num <= 12):
            raise ValueError("Invalid month")
    except ValueError:
        raise HTTPException(status_code=400, detail="Month must be in YYYY-MM format")
    
    repo = get_finance_repo()
    return await repo.get_interest_summary(month)


@router.get("/analytics/account/{account_type}/{account_id}", response_model=AccountAnalytics)
async def get_account_analytics(
    account_type: Literal["loan", "card"],
    account_id: int
):
    """Get detailed analytics for a specific account."""
    repo = get_finance_repo()
    analytics = await repo.get_account_analytics(account_type, account_id)
    
    if not analytics:
        raise HTTPException(status_code=404, detail="Account not found")
    
    return analytics


@router.get("/analytics/payment/{payment_id}", response_model=PaymentAnalytics)
async def get_payment_analytics(payment_id: int):
    """Get analytics for a specific payment."""
    repo = get_finance_repo()
    analytics = await repo.get_payment_analytics(payment_id)
    
    if not analytics:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    return analytics


# Peers management endpoints
@router.post("/peers")
async def add_peer(user_id: int, username: str):
    """Add a peer for notifications."""
    repo = get_finance_repo()
    await repo.add_peer_if_new(user_id, username)
    return {"message": "Peer added successfully"}


@router.get("/peers")
async def get_peers(exclude_id: Optional[int] = Query(None, description="Exclude user ID")):
    """Get peer IDs for notifications."""
    repo = get_finance_repo()
    peer_ids = await repo.get_peer_ids(exclude_id=exclude_id)
    return {"peer_ids": peer_ids}


# Budget alerts endpoints
@router.get("/alerts/check")
async def check_alert(category: str, month: str, threshold: int):
    """Check if threshold alert was already sent."""
    repo = get_finance_repo()
    was_notified = await repo.was_notified(category, month, threshold)
    return {"was_notified": was_notified}


@router.post("/alerts/mark")
async def mark_alert(category: str, month: str, threshold: int):
    """Mark threshold alert as sent."""
    repo = get_finance_repo()
    await repo.mark_notified(category, month, threshold)
    return {"message": "Alert marked as sent"}


# Bot support endpoints
@router.get("/accounts", response_model=AccountsOut)
async def get_accounts():
    """Get all active accounts for bot integration."""
    repo = get_finance_repo()
    return await repo.get_accounts()


@router.post("/payment", response_model=PaymentOut)
async def create_payment_bot(payment: PaymentCreate):
    """Create a payment (bot endpoint alias)."""
    repo = get_finance_repo()
    return await repo.create_payment(payment)
