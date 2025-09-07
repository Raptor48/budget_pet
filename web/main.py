from fastapi import FastAPI, HTTPException, Depends, Query, status
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import os
from datetime import datetime

from web.postgres_db import (
    get_expenses_for_month, add_expense, update_expense, delete_expense,
    get_month_report, list_limits, set_limit_and_apply, delete_category,
    get_current_month, get_remaining
)
from services.search_filter import matches
from services.logging_config import get_logger
# GitHub sync removed - using PostgreSQL directly
from web.schemas import (
    Expense, ExpenseCreate, ExpenseUpdate, ExpenseResponse,
    Limit, LimitCreate, ReportResponse, SyncStatus, HealthResponse
)
from web.deps import get_logger_service

# Initialize FastAPI app
app = FastAPI(title="Budget API", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    except Exception as e:
        logger.error("Startup: PostgreSQL connection failed: %s", e)

@app.get("/healthz", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(ok=True)

@app.get("/debug/env")
async def debug_env():
    """Debug endpoint to check environment variables."""
    return {
        "DATABASE_URL": os.getenv("DATABASE_URL", "NOT_SET"),
        "DATABASE_PUBLIC_URL": os.getenv("DATABASE_PUBLIC_URL", "NOT_SET"),
        "FASTAPI_INTERNAL_URL": os.getenv("FASTAPI_INTERNAL_URL", "NOT_SET"),
        "API_BASE_URL": os.getenv("API_BASE_URL", "NOT_SET")
    }

@app.get("/debug/db")
async def debug_db():
    """Debug endpoint to test database connection."""
    try:
        from web.postgres_db import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM expenses")
        count = cursor.fetchone()[0]
        conn.close()
        return {"status": "success", "expense_count": count}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.get("/expenses", response_model=List[Expense])
async def get_expenses(
    month: str = Query(..., description="Month in YYYY-MM format"),
    query: Optional[str] = Query(None, description="Search query for filtering")
):
    """Get expenses for a specific month with optional filtering."""
    try:
        expenses = get_expenses_for_month(month)

        # Apply search filter if provided
        if query:
            expenses = [e for e in expenses if matches(e, query)]

        # Convert to Expense objects
        result = []
        for expense_id, category, amount, date in expenses:
            result.append(Expense(
                id=expense_id,
                category=category,
                amount=float(amount),
                date=date
            ))

        return result
    except Exception as e:
        logger.error("Get expenses failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/expenses", response_model=ExpenseResponse)
async def create_expense(expense: ExpenseCreate):
    """Create a new expense."""
    try:
        exceeded, remaining = add_expense(expense.category, expense.amount)

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
            expense_update.amount or current_expense[2]
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
    sha = github_sync.get_current_sha() if github_sync else None
    return SyncStatus(sha=sha, last_sync=datetime.now().isoformat() if sha else None)

@app.post("/sync/pull", dependencies=[Depends(require_admin_key)])
async def sync_pull():
    """Force pull latest database from GitHub."""
    if not github_sync:
        raise HTTPException(status_code=400, detail="GitHub sync not configured")

    try:
        new_sha = github_sync.download_db()
        return {"message": "Database pulled successfully", "sha": new_sha}
    except Exception as e:
        logger.error("Sync pull failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sync/push", dependencies=[Depends(require_admin_key)])
async def sync_push():
    """Force push database to GitHub."""
    if not github_sync:
        raise HTTPException(status_code=400, detail="GitHub sync not configured")

    try:
        new_sha = github_sync.upload_db(github_sync.get_current_sha(), "API: manual push")
        return {"message": "Database pushed successfully", "sha": new_sha}
    except Exception as e:
        logger.error("Sync push failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
