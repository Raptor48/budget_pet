"""
Repository layer for finance module with PostgreSQL operations.
All money amounts stored as integer cents.
"""

import os
from decimal import Decimal
from datetime import date, datetime
from typing import List, Optional, Tuple, Dict, Literal
import asyncpg
from .models import (
    LoanCreate, LoanUpdate, LoanOut,
    CreditCardCreate, CreditCardUpdate, CreditCardOut,
    PaymentCreate, PaymentOut,
    IncomeCreate, IncomeUpdate, IncomeOut,
    SummaryOut, DebtTotals, LoanEstimatedClose, AccountsOut, AccountSummary,
    InterestSummary, AccountAnalytics, MonthlyInterest, PaymentAnalytics
)
from .calculations import generate_interest_summary, calculate_payment_analytics


class FinanceRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None

    async def get_pool(self) -> asyncpg.Pool:
        """Get or create connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.database_url)
        return self._pool

    async def close(self):
        """Close connection pool."""
        if self._pool:
            await self._pool.close()

    async def init_tables(self):
        """Create tables if they don't exist."""
        pool = await self.get_pool()
        
        ddl_queries = [
            """
            CREATE TABLE IF NOT EXISTS finance_loans (
              id SERIAL PRIMARY KEY,
              name TEXT NOT NULL,
              category_name TEXT NOT NULL,
              apr_percent NUMERIC(6,3) NOT NULL DEFAULT 0,
              current_balance_cents BIGINT NOT NULL DEFAULT 0,
              due_date DATE,
              min_payment_cents BIGINT NOT NULL DEFAULT 0,
              remaining_months INT,
              close_date DATE,
              is_active BOOLEAN NOT NULL DEFAULT TRUE,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_finance_loans_active ON finance_loans(is_active)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_finance_loans_category ON finance_loans(category_name)
            """,
            """
            CREATE TABLE IF NOT EXISTS finance_credit_cards (
              id SERIAL PRIMARY KEY,
              name TEXT NOT NULL,
              category_name TEXT NOT NULL,
              apr_percent NUMERIC(6,3) NOT NULL DEFAULT 0,
              current_balance_cents BIGINT NOT NULL DEFAULT 0,
              credit_limit_cents BIGINT,
              due_date DATE,
              min_payment_cents BIGINT NOT NULL DEFAULT 0,
              is_active BOOLEAN NOT NULL DEFAULT TRUE,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_finance_cc_active ON finance_credit_cards(is_active)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_finance_cc_category ON finance_credit_cards(category_name)
            """,
            """
            CREATE TABLE IF NOT EXISTS finance_payments (
              id SERIAL PRIMARY KEY,
              account_type TEXT NOT NULL CHECK (account_type IN ('loan','card')),
              account_id INT NOT NULL,
              amount_cents BIGINT NOT NULL,
              occurred_at DATE NOT NULL,
              person TEXT CHECK (person IN ('Denis','Taya')),
              note TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_finance_payments_account ON finance_payments(account_type, account_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_finance_payments_date ON finance_payments(occurred_at)
            """,
            """
            CREATE TABLE IF NOT EXISTS finance_income (
              id SERIAL PRIMARY KEY,
              person TEXT NOT NULL CHECK (person IN ('Denis','Taya')),
              amount_cents BIGINT NOT NULL,
              occurred_at DATE NOT NULL,
              note TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_finance_income_date ON finance_income(occurred_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_finance_income_person ON finance_income(person)
            """
        ]

        async with pool.acquire() as conn:
            for query in ddl_queries:
                await conn.execute(query)

    # Loans CRUD
    async def get_loans(self, active_only: bool = True) -> List[LoanOut]:
        """Get all loans, optionally filtered by active status."""
        pool = await self.get_pool()
        query = """
            SELECT id, name, category_name, apr_percent, current_balance_cents,
                   due_date, min_payment_cents, remaining_months, close_date,
                   is_active, created_at, updated_at
            FROM finance_loans
        """
        if active_only:
            query += " WHERE is_active = TRUE"
        query += " ORDER BY created_at DESC"

        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [LoanOut(**dict(row)) for row in rows]

    async def create_loan(self, loan: LoanCreate) -> LoanOut:
        """Create a new loan."""
        pool = await self.get_pool()
        query = """
            INSERT INTO finance_loans (name, category_name, apr_percent, current_balance_cents,
                                     due_date, min_payment_cents, remaining_months, close_date, is_active)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id, name, category_name, apr_percent, current_balance_cents,
                      due_date, min_payment_cents, remaining_months, close_date,
                      is_active, created_at, updated_at
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                loan.name, loan.category_name, float(loan.apr_percent),
                loan.current_balance_cents, loan.due_date, loan.min_payment_cents,
                loan.remaining_months, loan.close_date, loan.is_active
            )
            return LoanOut(**dict(row))

    async def update_loan(self, loan_id: int, loan: LoanUpdate) -> Optional[LoanOut]:
        """Update a loan."""
        pool = await self.get_pool()
        
        # Build dynamic update query
        updates = []
        params = []
        param_count = 1

        if loan.name is not None:
            updates.append(f"name = ${param_count}")
            params.append(loan.name)
            param_count += 1
        if loan.category_name is not None:
            updates.append(f"category_name = ${param_count}")
            params.append(loan.category_name)
            param_count += 1
        if loan.apr_percent is not None:
            updates.append(f"apr_percent = ${param_count}")
            params.append(float(loan.apr_percent))
            param_count += 1
        if loan.current_balance_cents is not None:
            updates.append(f"current_balance_cents = ${param_count}")
            params.append(loan.current_balance_cents)
            param_count += 1
        if loan.due_date is not None:
            updates.append(f"due_date = ${param_count}")
            params.append(loan.due_date)
            param_count += 1
        if loan.min_payment_cents is not None:
            updates.append(f"min_payment_cents = ${param_count}")
            params.append(loan.min_payment_cents)
            param_count += 1
        if loan.remaining_months is not None:
            updates.append(f"remaining_months = ${param_count}")
            params.append(loan.remaining_months)
            param_count += 1
        if loan.close_date is not None:
            updates.append(f"close_date = ${param_count}")
            params.append(loan.close_date)
            param_count += 1
        if loan.is_active is not None:
            updates.append(f"is_active = ${param_count}")
            params.append(loan.is_active)
            param_count += 1

        if not updates:
            return await self.get_loan(loan_id)

        updates.append("updated_at = NOW()")
        params.append(loan_id)

        query = f"""
            UPDATE finance_loans 
            SET {', '.join(updates)}
            WHERE id = ${param_count}
            RETURNING id, name, category_name, apr_percent, current_balance_cents,
                      due_date, min_payment_cents, remaining_months, close_date,
                      is_active, created_at, updated_at
        """

        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            return LoanOut(**dict(row)) if row else None

    async def get_loan(self, loan_id: int) -> Optional[LoanOut]:
        """Get a loan by ID."""
        pool = await self.get_pool()
        query = """
            SELECT id, name, category_name, apr_percent, current_balance_cents,
                   due_date, min_payment_cents, remaining_months, close_date,
                   is_active, created_at, updated_at
            FROM finance_loans
            WHERE id = $1
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, loan_id)
            return LoanOut(**dict(row)) if row else None

    async def delete_loan(self, loan_id: int) -> bool:
        """Soft delete a loan (set is_active=False)."""
        pool = await self.get_pool()
        query = """
            UPDATE finance_loans 
            SET is_active = FALSE, updated_at = NOW()
            WHERE id = $1
        """
        async with pool.acquire() as conn:
            result = await conn.execute(query, loan_id)
            return result == "UPDATE 1"

    # Credit Cards CRUD
    async def get_cards(self, active_only: bool = True) -> List[CreditCardOut]:
        """Get all credit cards, optionally filtered by active status."""
        pool = await self.get_pool()
        query = """
            SELECT id, name, category_name, apr_percent, current_balance_cents,
                   credit_limit_cents, due_date, min_payment_cents,
                   is_active, created_at, updated_at
            FROM finance_credit_cards
        """
        if active_only:
            query += " WHERE is_active = TRUE"
        query += " ORDER BY created_at DESC"

        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [CreditCardOut(**dict(row)) for row in rows]

    async def create_card(self, card: CreditCardCreate) -> CreditCardOut:
        """Create a new credit card."""
        pool = await self.get_pool()
        query = """
            INSERT INTO finance_credit_cards (name, category_name, apr_percent, current_balance_cents,
                                            credit_limit_cents, due_date, min_payment_cents, is_active)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id, name, category_name, apr_percent, current_balance_cents,
                      credit_limit_cents, due_date, min_payment_cents,
                      is_active, created_at, updated_at
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                card.name, card.category_name, float(card.apr_percent),
                card.current_balance_cents, card.credit_limit_cents,
                card.due_date, card.min_payment_cents, card.is_active
            )
            return CreditCardOut(**dict(row))

    async def update_card(self, card_id: int, card: CreditCardUpdate) -> Optional[CreditCardOut]:
        """Update a credit card."""
        pool = await self.get_pool()
        
        # Build dynamic update query
        updates = []
        params = []
        param_count = 1

        if card.name is not None:
            updates.append(f"name = ${param_count}")
            params.append(card.name)
            param_count += 1
        if card.category_name is not None:
            updates.append(f"category_name = ${param_count}")
            params.append(card.category_name)
            param_count += 1
        if card.apr_percent is not None:
            updates.append(f"apr_percent = ${param_count}")
            params.append(float(card.apr_percent))
            param_count += 1
        if card.current_balance_cents is not None:
            updates.append(f"current_balance_cents = ${param_count}")
            params.append(card.current_balance_cents)
            param_count += 1
        if card.credit_limit_cents is not None:
            updates.append(f"credit_limit_cents = ${param_count}")
            params.append(card.credit_limit_cents)
            param_count += 1
        if card.due_date is not None:
            updates.append(f"due_date = ${param_count}")
            params.append(card.due_date)
            param_count += 1
        if card.min_payment_cents is not None:
            updates.append(f"min_payment_cents = ${param_count}")
            params.append(card.min_payment_cents)
            param_count += 1
        if card.is_active is not None:
            updates.append(f"is_active = ${param_count}")
            params.append(card.is_active)
            param_count += 1

        if not updates:
            return await self.get_card(card_id)

        updates.append("updated_at = NOW()")
        params.append(card_id)

        query = f"""
            UPDATE finance_credit_cards 
            SET {', '.join(updates)}
            WHERE id = ${param_count}
            RETURNING id, name, category_name, apr_percent, current_balance_cents,
                      credit_limit_cents, due_date, min_payment_cents,
                      is_active, created_at, updated_at
        """

        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            return CreditCardOut(**dict(row)) if row else None

    async def get_card(self, card_id: int) -> Optional[CreditCardOut]:
        """Get a credit card by ID."""
        pool = await self.get_pool()
        query = """
            SELECT id, name, category_name, apr_percent, current_balance_cents,
                   credit_limit_cents, due_date, min_payment_cents,
                   is_active, created_at, updated_at
            FROM finance_credit_cards
            WHERE id = $1
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, card_id)
            return CreditCardOut(**dict(row)) if row else None

    async def delete_card(self, card_id: int) -> bool:
        """Soft delete a credit card (set is_active=False)."""
        pool = await self.get_pool()
        query = """
            UPDATE finance_credit_cards 
            SET is_active = FALSE, updated_at = NOW()
            WHERE id = $1
        """
        async with pool.acquire() as conn:
            result = await conn.execute(query, card_id)
            return result == "UPDATE 1"

    # Payments
    async def create_payment(self, payment: PaymentCreate) -> PaymentOut:
        """Create a payment and update account balance."""
        pool = await self.get_pool()
        
        # Use provided date or default to today
        payment_date = payment.occurred_at if payment.occurred_at else date.today()
        
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Insert payment
                payment_query = """
                    INSERT INTO finance_payments (account_type, account_id, amount_cents, 
                                                occurred_at, person, note)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id, account_type, account_id, amount_cents, occurred_at, 
                              person, note, created_at
                """
                payment_row = await conn.fetchrow(
                    payment_query,
                    payment.account_type, payment.account_id, payment.amount_cents,
                    payment_date, payment.person, payment.note
                )

                # Update account balance
                if payment.account_type == "loan":
                    update_query = """
                        UPDATE finance_loans 
                        SET current_balance_cents = GREATEST(0, current_balance_cents - $1),
                            updated_at = NOW()
                        WHERE id = $2
                    """
                else:  # card
                    update_query = """
                        UPDATE finance_credit_cards 
                        SET current_balance_cents = GREATEST(0, current_balance_cents - $1),
                            updated_at = NOW()
                        WHERE id = $2
                    """
                
                await conn.execute(update_query, payment.amount_cents, payment.account_id)

                return PaymentOut(**dict(payment_row))

    async def get_payments(self, account_type: Optional[str] = None, 
                          account_id: Optional[int] = None,
                          start_date: Optional[date] = None,
                          end_date: Optional[date] = None) -> List[PaymentOut]:
        """Get payments with optional filters."""
        pool = await self.get_pool()
        
        query = """
            SELECT id, account_type, account_id, amount_cents, occurred_at, 
                   person, note, created_at
            FROM finance_payments
            WHERE 1=1
        """
        params = []
        param_count = 1

        if account_type:
            query += f" AND account_type = ${param_count}"
            params.append(account_type)
            param_count += 1
        if account_id:
            query += f" AND account_id = ${param_count}"
            params.append(account_id)
            param_count += 1
        if start_date:
            query += f" AND occurred_at >= ${param_count}"
            params.append(start_date)
            param_count += 1
        if end_date:
            query += f" AND occurred_at <= ${param_count}"
            params.append(end_date)
            param_count += 1

        query += " ORDER BY occurred_at DESC"

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [PaymentOut(**dict(row)) for row in rows]

    # Income CRUD
    async def get_income(self, month: Optional[str] = None, 
                        person: Optional[Literal["Denis", "Taya"]] = None) -> List[IncomeOut]:
        """Get income entries with optional month and person filters."""
        pool = await self.get_pool()
        
        query = """
            SELECT id, person, amount_cents, occurred_at, note, created_at
            FROM finance_income
            WHERE 1=1
        """
        params = []
        param_count = 1

        if month:
            year, month_num = map(int, month.split('-'))
            start_date = date(year, month_num, 1)
            if month_num == 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, month_num + 1, 1)
            
            query += f" AND occurred_at >= ${param_count} AND occurred_at < ${param_count + 1}"
            params.extend([start_date, end_date])
            param_count += 2

        if person:
            query += f" AND person = ${param_count}"
            params.append(person)
            param_count += 1

        query += " ORDER BY occurred_at DESC"

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [IncomeOut(**dict(row)) for row in rows]

    async def create_income(self, income: IncomeCreate) -> IncomeOut:
        """Create a new income entry."""
        pool = await self.get_pool()
        
        # Use provided date or default to today
        income_date = income.occurred_at if income.occurred_at else date.today()
        
        query = """
            INSERT INTO finance_income (person, amount_cents, occurred_at, note)
            VALUES ($1, $2, $3, $4)
            RETURNING id, person, amount_cents, occurred_at, note, created_at
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                income.person, income.amount_cents, income_date, income.note
            )
            return IncomeOut(**dict(row))

    async def update_income(self, income_id: int, income: IncomeUpdate) -> Optional[IncomeOut]:
        """Update an income entry."""
        pool = await self.get_pool()
        
        # Build dynamic update query
        updates = []
        params = []
        param_count = 1

        if income.person is not None:
            updates.append(f"person = ${param_count}")
            params.append(income.person)
            param_count += 1
        if income.amount_cents is not None:
            updates.append(f"amount_cents = ${param_count}")
            params.append(income.amount_cents)
            param_count += 1
        if income.occurred_at is not None:
            updates.append(f"occurred_at = ${param_count}")
            params.append(income.occurred_at)
            param_count += 1
        if income.note is not None:
            updates.append(f"note = ${param_count}")
            params.append(income.note)
            param_count += 1

        if not updates:
            return await self.get_income_by_id(income_id)

        params.append(income_id)

        query = f"""
            UPDATE finance_income 
            SET {', '.join(updates)}
            WHERE id = ${param_count}
            RETURNING id, person, amount_cents, occurred_at, note, created_at
        """

        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            return IncomeOut(**dict(row)) if row else None

    async def get_income_by_id(self, income_id: int) -> Optional[IncomeOut]:
        """Get income entry by ID."""
        pool = await self.get_pool()
        query = """
            SELECT id, person, amount_cents, occurred_at, note, created_at
            FROM finance_income
            WHERE id = $1
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, income_id)
            return IncomeOut(**dict(row)) if row else None

    async def delete_income(self, income_id: int) -> bool:
        """Delete an income entry."""
        pool = await self.get_pool()
        query = "DELETE FROM finance_income WHERE id = $1"
        async with pool.acquire() as conn:
            result = await conn.execute(query, income_id)
            return result == "DELETE 1"

    # Summary calculations
    async def get_summary(self, month: str) -> SummaryOut:
        """Get financial summary for a month."""
        pool = await self.get_pool()
        
        # Parse month
        year, month_num = map(int, month.split('-'))
        start_date = date(year, month_num, 1)
        if month_num == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month_num + 1, 1)

        async with pool.acquire() as conn:
            # Income totals
            income_query = """
                SELECT person, SUM(amount_cents) as total
                FROM finance_income
                WHERE occurred_at >= $1 AND occurred_at < $2
                GROUP BY person
            """
            income_rows = await conn.fetch(income_query, start_date, end_date)
            
            income_by_person = {"Denis": 0, "Taya": 0}
            income_total = 0
            for row in income_rows:
                person = row["person"]
                amount = row["total"]
                income_by_person[person] = amount
                income_total += amount

            # Debt totals - separate queries
            loans_query = """
                SELECT 
                    COALESCE(SUM(CASE WHEN is_active THEN current_balance_cents ELSE 0 END), 0) as loans_balance,
                    COALESCE(SUM(CASE WHEN is_active THEN min_payment_cents ELSE 0 END), 0) as loans_min_payment
                FROM finance_loans
            """
            loans_row = await conn.fetchrow(loans_query)
            loans_balance = loans_row["loans_balance"] if loans_row else 0
            loans_min_payment = loans_row["loans_min_payment"] if loans_row else 0
            
            cards_query = """
                SELECT 
                    COALESCE(SUM(CASE WHEN is_active THEN current_balance_cents ELSE 0 END), 0) as cards_balance,
                    COALESCE(SUM(CASE WHEN is_active THEN min_payment_cents ELSE 0 END), 0) as cards_min_payment
                FROM finance_credit_cards
            """
            cards_row = await conn.fetchrow(cards_query)
            cards_balance = cards_row["cards_balance"] if cards_row else 0
            cards_min_payment = cards_row["cards_min_payment"] if cards_row else 0

            # Loans with estimated close dates
            loans_close_query = """
                SELECT id, name, remaining_months
                FROM finance_loans
                WHERE is_active = TRUE AND remaining_months IS NOT NULL
                ORDER BY remaining_months
            """
            loans_rows = await conn.fetch(loans_close_query)
            
            loans_estimated_close = []
            for row in loans_rows:
                # Calculate estimated close date
                estimated_close = start_date.replace(day=1)
                for _ in range(row["remaining_months"]):
                    if estimated_close.month == 12:
                        estimated_close = estimated_close.replace(year=estimated_close.year + 1, month=1)
                    else:
                        estimated_close = estimated_close.replace(month=estimated_close.month + 1)
                
                loans_estimated_close.append(LoanEstimatedClose(
                    loan_id=row["id"],
                    name=row["name"],
                    remaining_months=row["remaining_months"],
                    estimated_close_date=estimated_close
                ))

            debt_totals = DebtTotals(
                loans_balance_cents=loans_balance,
                cards_balance_cents=cards_balance,
                combined_balance_cents=loans_balance + cards_balance,
                loans_min_payment_cents=loans_min_payment,
                cards_min_payment_cents=cards_min_payment,
                min_payments_cents=loans_min_payment + cards_min_payment
            )

            return SummaryOut(
                month=month,
                income_total_cents=income_total,
                income_by_person=income_by_person,
                debt_totals=debt_totals,
                loans_estimated_close=loans_estimated_close
            )

    # Interest and analytics
    async def get_interest_summary(self, month: str) -> InterestSummary:
        """Get comprehensive interest and analytics summary for a month."""
        loans = await self.get_loans(active_only=True)
        cards = await self.get_cards(active_only=True)
        
        # Get payments for the last 6 months for average calculation
        year, month_num = map(int, month.split('-'))
        start_date = date(year, month_num, 1)
        
        # Go back 6 months for payment history
        history_start = start_date
        for _ in range(6):
            if history_start.month == 1:
                history_start = history_start.replace(year=history_start.year - 1, month=12)
            else:
                history_start = history_start.replace(month=history_start.month - 1)
        
        payments = await self.get_payments(start_date=history_start)
        
        return generate_interest_summary(month, loans, cards, payments)
    
    async def get_account_analytics(self, account_type: str, account_id: int) -> Optional[AccountAnalytics]:
        """Get detailed analytics for a specific account."""
        if account_type == "loan":
            account = await self.get_loan(account_id)
            if not account:
                return None
        else:  # card
            account = await self.get_card(account_id)
            if not account:
                return None
        
        # Get payment history for this account
        payments = await self.get_payments(account_type=account_type, account_id=account_id)
        
        from .calculations import calculate_account_analytics, calculate_average_payment
        
        avg_payment = calculate_average_payment(payments) or account.min_payment_cents
        
        return calculate_account_analytics(
            account_id=account.id,
            account_type=account_type,
            name=account.name,
            current_balance_cents=account.current_balance_cents,
            apr_percent=account.apr_percent,
            min_payment_cents=account.min_payment_cents,
            average_payment_cents=avg_payment
        )
    
    async def get_payment_analytics(self, payment_id: int) -> Optional[PaymentAnalytics]:
        """Get analytics for a specific payment."""
        pool = await self.get_pool()
        
        async with pool.acquire() as conn:
            # Get payment details
            payment_query = """
                SELECT id, account_type, account_id, amount_cents, occurred_at, 
                       person, note, created_at
                FROM finance_payments
                WHERE id = $1
            """
            payment_row = await conn.fetchrow(payment_query, payment_id)
            if not payment_row:
                return None
            
            payment = PaymentOut(**dict(payment_row))
            
            # Get account details to calculate balance before payment
            if payment.account_type == "loan":
                account_query = """
                    SELECT current_balance_cents, apr_percent
                    FROM finance_loans
                    WHERE id = $1
                """
            else:  # card
                account_query = """
                    SELECT current_balance_cents, apr_percent
                    FROM finance_credit_cards
                    WHERE id = $1
                """
            
            account_row = await conn.fetchrow(account_query, payment.account_id)
            if not account_row:
                return None
            
            # Current balance + payment amount = balance before payment
            balance_before = account_row["current_balance_cents"] + payment.amount_cents
            apr_percent = Decimal(str(account_row["apr_percent"]))
            
            return calculate_payment_analytics(payment, balance_before, apr_percent)

    # Bot support
    async def get_accounts(self) -> AccountsOut:
        """Get all active accounts for bot integration."""
        loans = await self.get_loans(active_only=True)
        cards = await self.get_cards(active_only=True)
        
        return AccountsOut(
            loans=[AccountSummary(id=loan.id, name=loan.name, category_name=loan.category_name) 
                   for loan in loans],
            cards=[AccountSummary(id=card.id, name=card.name, category_name=card.category_name) 
                   for card in cards]
        )


# Global repository instance
_finance_repo: Optional[FinanceRepository] = None


def get_finance_repo() -> FinanceRepository:
    """Get finance repository instance."""
    global _finance_repo
    if _finance_repo is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable not set")
        _finance_repo = FinanceRepository(database_url)
    return _finance_repo
