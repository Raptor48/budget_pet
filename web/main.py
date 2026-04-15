from fastapi import FastAPI, HTTPException, Depends, Query, status
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from web.postgres_db import (
    get_expenses_for_month, add_expense, update_expense, delete_expense,
    get_month_report, list_limits, set_limit_and_apply, delete_category,
    get_current_month, get_remaining, rename_category
)
from services.search_filter import matches
# GitHub sync removed - using PostgreSQL directly
from web.schemas import (
    Expense, ExpenseCreate, ExpenseUpdate, ExpenseResponse,
    Limit, LimitCreate, ReportResponse, SyncStatus, HealthResponse
)
from web.deps import get_logger_service
from web.finance import api_router as finance_api_router, get_finance_repo
from web.auth import auth_router, AuthMiddleware
from web.plaid import plaid_router, init_plaid_repo, start_scheduler

# Initialize FastAPI app
app = FastAPI(title="Budget API", version="1.0.0")


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Local development
        "https://nextjs-production-4840.up.railway.app",  # Production frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],  # Expose headers for Safari compatibility
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Add authentication middleware
app.add_middleware(AuthMiddleware)

# Global services
logger = get_logger_service()

# Admin key for sync endpoints (optional)
ADMIN_KEY = os.getenv("ADMIN_KEY")

def require_admin_key(x_admin_key: Optional[str] = None):
    """Require admin key for sensitive endpoints."""
    if ADMIN_KEY and x_admin_key != ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin key required"
        )

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    logger.info("Starting Budget API server")
    
    try:
        # Test PostgreSQL connection
        from web.postgres_db import get_db_connection
        conn = get_db_connection()
        conn.close()
        logger.info("Startup: PostgreSQL connection successful")
        
        # Initialize finance tables
        finance_repo = get_finance_repo()
        await finance_repo.init_tables()
        logger.info("Startup: Finance tables initialized")

        # Initialize Plaid tables and scheduler (only if credentials are configured)
        if os.getenv("PLAID_CLIENT_ID") and os.getenv("PLAID_ENCRYPTION_KEY"):
            await init_plaid_repo()
            start_scheduler()
            logger.info("Startup: Plaid integration initialized")
        else:
            logger.info("Startup: Plaid not configured (PLAID_CLIENT_ID or PLAID_ENCRYPTION_KEY missing)")
    except Exception as e:
        logger.error("Startup: PostgreSQL connection failed: %s", e)

@app.get("/healthz", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(ok=True)


@app.get("/expenses", response_model=List[Expense])
async def get_expenses(
    month: str = Query(..., description="Month in YYYY-MM format"),
    query: Optional[str] = Query(None, description="Search query for filtering"),
    source: Optional[str] = Query(None, description="Filter by source: manual, plaid, plaid_sandbox")
):
    """Get expenses for a specific month with optional filtering."""
    try:
        expenses = get_expenses_for_month(month)

        if query:
            expenses = [e for e in expenses if matches(e, query)]

        if source:
            expenses = [e for e in expenses if e[4] == source]

        result = []
        for expense_id, category, amount, date, src in expenses:
            result.append(Expense(
                id=expense_id,
                category=category,
                amount=float(amount),
                date=date,
                source=src
            ))

        return result
    except Exception as e:
        logger.error("Get expenses failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/expenses", response_model=ExpenseResponse)
async def create_expense(expense: ExpenseCreate):
    """Create a new expense."""
    try:
        # Use provided date or default to today
        expense_date = expense.date if expense.date else None
        exceeded, remaining = add_expense(expense.category, expense.amount, expense_date)

        # GitHub sync disabled to prevent unnecessary redeploys

        return ExpenseResponse(exceeded=exceeded, remaining=remaining)
    except Exception as e:
        logger.error("Create expense failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/expenses/{expense_id}", response_model=ExpenseResponse)
async def update_expense_endpoint(expense_id: int, expense_update: ExpenseUpdate):
    """Update an existing expense."""
    try:
        # Get current expense to log the change
        expenses = get_expenses_for_month(get_current_month())
        current_expense = next((e for e in expenses if e[0] == expense_id), None)
        if not current_expense:
            raise HTTPException(status_code=404, detail="Expense not found")

        # Update expense
        update_expense(
            expense_id,
            expense_update.category or current_expense[1],
            expense_update.amount or current_expense[2],
            expense_update.date
        )

        # Calculate remaining after update
        remaining = get_remaining(expense_update.category or current_expense[1], get_current_month())

        # GitHub sync disabled to prevent unnecessary redeploys

        return ExpenseResponse(exceeded=remaining < 0, remaining=remaining)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Update expense failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/expenses/{expense_id}")
async def delete_expense_endpoint(expense_id: int):
    """Delete an expense."""
    try:
        delete_expense(expense_id)

        # GitHub sync disabled to prevent unnecessary redeploys

        return {"message": "Expense deleted successfully"}
    except Exception as e:
        logger.error("Delete expense failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/report", response_model=ReportResponse)
async def get_report(
    month: str = Query(..., description="Month in YYYY-MM format"),
    compare: Optional[str] = Query(None, description="Compare month in YYYY-MM format")
):
    """Get monthly report with optional comparison."""
    try:
        report = get_month_report(month)
        comparison = None

        if compare:
            compare_report = get_month_report(compare)
            comparison = {}
            for category in set(report.keys()) | set(compare_report.keys()):
                current_spent = report.get(category, {}).get("spent", 0.0)
                compare_spent = compare_report.get(category, {}).get("spent", 0.0)
                if compare_spent > 0:
                    comparison[category] = ((current_spent - compare_spent) / compare_spent) * 100

        return ReportResponse(report=report, comparison=comparison)
    except Exception as e:
        logger.error("Get report failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/limits", response_model=List[Limit])
async def get_limits():
    """Get all category limits."""
    try:
        limits = list_limits()
        return [Limit(category=name, default_limit=float(limit)) for name, limit in limits]
    except Exception as e:
        logger.error("Get limits failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/limits", response_model=Limit)
async def create_or_update_limit(limit: LimitCreate):
    """Create or update a category limit."""
    try:
        set_limit_and_apply(limit.category, limit.default_limit, get_current_month())

        # GitHub sync disabled to prevent unnecessary redeploys

        return Limit(category=limit.category, default_limit=limit.default_limit)
    except Exception as e:
        logger.error("Create/update limit failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/limits/{category_name}", response_model=Limit)
async def update_limit_endpoint(category_name: str, limit_update: dict):
    """Update a category limit or name."""
    try:
        # Check if updating category name
        if "category" in limit_update:
            new_name = limit_update["category"]
            # Rename category in limits table
            rename_category(category_name, new_name)
            # Update limit if provided
            if "default_limit" in limit_update:
                set_limit_and_apply(new_name, limit_update["default_limit"], get_current_month())
            return Limit(category=new_name, default_limit=limit_update.get("default_limit", 0))
        else:
            # Update limit only
            set_limit_and_apply(category_name, limit_update["default_limit"], get_current_month())
            return Limit(category=category_name, default_limit=limit_update["default_limit"])

        # GitHub sync disabled to prevent unnecessary redeploys

    except Exception as e:
        logger.error("Update limit failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/limits/{category_name}")
async def delete_limit_endpoint(category_name: str):
    """Delete a category limit."""
    try:
        delete_category(category_name)

        # GitHub sync disabled to prevent unnecessary redeploys

        return {"message": f"Category '{category_name}' deleted successfully"}
    except Exception as e:
        logger.error("Delete limit failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/categories/{category_name}")
async def delete_category_endpoint(category_name: str):
    """Delete a category and all its expenses."""
    try:
        delete_category(category_name)

        # GitHub sync disabled to prevent unnecessary redeploys

        return {"message": f"Category '{category_name}' deleted successfully"}
    except Exception as e:
        logger.error("Delete category failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sync/status", response_model=SyncStatus)
async def get_sync_status():
    """Get current sync status."""
    # GitHub sync disabled - using PostgreSQL directly
    return SyncStatus(sha=None, last_sync=None)

@app.post("/sync/pull", dependencies=[Depends(require_admin_key)])
async def sync_pull():
    """Force pull latest database from GitHub."""
    raise HTTPException(status_code=400, detail="GitHub sync not configured - using PostgreSQL directly")

@app.post("/sync/push", dependencies=[Depends(require_admin_key)])
async def sync_push():
    """Force push database to GitHub."""
    raise HTTPException(status_code=400, detail="GitHub sync not configured - using PostgreSQL directly")

# Include routers
app.include_router(auth_router)
app.include_router(finance_api_router)
app.include_router(plaid_router)
