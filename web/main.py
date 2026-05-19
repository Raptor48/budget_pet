"""
Budget Pet V2 — FastAPI application entry point.
All routes are under /api/* and protected by AuthMiddleware.
"""
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from web.version import APP_VERSION

load_dotenv()

logger = logging.getLogger(__name__)


def _cors_allow_origins() -> list[str]:
    """Comma-separated browser origins in CORS_ORIGINS (session cookies).

    The production Next.js origin is always supplied via the `CORS_ORIGINS`
    env var in Railway; the defaults below cover local development only so
    we never hardcode a specific deployment host in the source.
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


# ---------------------------------------------------------------------------
# App + Middleware
# ---------------------------------------------------------------------------

app = FastAPI(title="Budget Pet API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

from web.auth import AuthMiddleware  # noqa: E402 — must be after app creation

app.add_middleware(AuthMiddleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

from web.auth import auth_router  # noqa: E402
from web.accounts import router as accounts_router  # noqa: E402
from web.categories import router as categories_router  # noqa: E402
from web.tags import router as tags_router  # noqa: E402
from web.transactions import router as transactions_router  # noqa: E402
from web.recurring import router as recurring_router  # noqa: E402
from web.budgets import router as budgets_router  # noqa: E402
from web.investments import router as investments_router  # noqa: E402
from web.reports import router as reports_router  # noqa: E402
from web.plaid import plaid_router  # noqa: E402
from web.piggy import router as piggy_router  # noqa: E402
from web.merchant_rules import (  # noqa: E402
    merchant_aliases_router,
    merchant_rules_router,
)
from web.insights import insights_router  # noqa: E402
from web.app_settings import app_settings_router  # noqa: E402
from web.internal_transfers import internal_transfers_router  # noqa: E402
from web.audit import audit_router  # noqa: E402
from web.bot_api import router as bot_router  # noqa: E402
from web.telegram import router as telegram_router  # noqa: E402

app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(categories_router)
app.include_router(tags_router)
app.include_router(transactions_router)
app.include_router(recurring_router)
app.include_router(budgets_router)
app.include_router(investments_router)
app.include_router(reports_router)
app.include_router(plaid_router)
app.include_router(piggy_router)
app.include_router(merchant_rules_router)
app.include_router(merchant_aliases_router)
app.include_router(insights_router)
app.include_router(app_settings_router)
app.include_router(internal_transfers_router)
app.include_router(audit_router)
# Bot + Telegram webhook routes are registered only when a bot token is
# configured. Without TELEGRAM_BOT_TOKEN there's nothing they can do (the
# bot runtime no-ops at startup too) and exposing them just adds attack
# surface in demo / portfolio deployments. Restart required to flip.
if (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip():
    app.include_router(bot_router)
    app.include_router(telegram_router)

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def startup_event():
    """Initialize the application on startup."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting Budget Pet V2 API")

    # 1. Validate required auth env vars
    from web.auth.routes import validate_admin_credentials
    validate_admin_credentials()

    # 2. Get the shared asyncpg pool (creates it if not yet initialized)
    from web.db import get_pool
    pool = await get_pool()

    # 3. Run auth DB migrations (users + sessions)
    from web.auth.db_migration import run_migrations
    await run_migrations()
    logger.info("Auth migrations applied")

    # 4. Run V2 schema migrations
    from web.migrations.v2_init import run_v2_migrations
    await run_v2_migrations(pool)
    logger.info("V2 schema migrations applied")

    # 5. Bot v1 migrations — telegram link, chores, notifications, receipts.
    #    Idempotent; safe to run on every startup.
    from web.migrations.bot_v1 import run_bot_migrations
    await run_bot_migrations(pool)

    # DISABLE_SCHEDULERS lets a local dev process connect to the production
    # DB without firing the Plaid sync, notification producers, or dispatcher
    # on top of the Railway instance's own jobs. Read once here so the flag
    # is visible to operators in the startup log.
    schedulers_disabled = os.getenv("DISABLE_SCHEDULERS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }

    # 6. Ensure plaid_items + plaid_sync_log tables exist
    if os.getenv("PLAID_CLIENT_ID"):
        from web.plaid.repo import get_plaid_repo
        repo = get_plaid_repo()
        await repo.init_tables()
        # Best-effort fill-in of missing institution logos via Brandfetch
        # (Plaid doesn't return one for some banks, Chase being the famous
        # example). Idempotent: only touches rows where institution_logo
        # IS NULL, so re-running on every boot is cheap once filled.
        try:
            filled = await repo.backfill_missing_institution_logos()
            if filled:
                logger.info(
                    "Brandfetch: filled %d missing institution logo(s)",
                    filled,
                )
        except Exception as exc:
            logger.warning("Brandfetch institution backfill failed: %s", exc)
        if schedulers_disabled:
            logger.info("Plaid tables ensured — scheduler skipped (DISABLE_SCHEDULERS)")
        else:
            from web.plaid.scheduler import start_scheduler
            start_scheduler()
            logger.info("Plaid integration initialized and scheduler started")
    else:
        logger.info("Plaid not configured — skipping Plaid setup")

    # 7. Telegram bot — webhook mode, runs in-process via FastAPI.
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        from web.telegram.runtime import start_bot_runtime
        await start_bot_runtime()
        logger.info("Telegram bot runtime initialized")
    else:
        logger.info("Telegram bot not configured — skipping bot startup")

    # 8. Notification dispatcher — drains notifications_queue every minute.
    if schedulers_disabled:
        logger.info("Notification dispatcher skipped (DISABLE_SCHEDULERS)")
    else:
        from web.notifications.dispatcher import start_dispatcher
        start_dispatcher()
        logger.info("Notification dispatcher started")


@app.on_event("shutdown")
async def shutdown_event():
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        try:
            from web.telegram.runtime import stop_bot_runtime
            await stop_bot_runtime()
        except Exception:
            logger.exception("Failed to stop Telegram bot runtime cleanly")
    from web.db import close_pool
    await close_pool()
    logger.info("Shutdown complete")


@app.get("/healthz")
async def health_check():
    return {"ok": True, "version": APP_VERSION}
