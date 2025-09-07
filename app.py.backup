from services.env_loader import load_env_multi
from services.logging_config import get_logger
from services.github_sync import GithubSync
from bd import DB_FILE
from ui.main_window import BudgetApp
from pathlib import Path
from datetime import datetime
import os

def main():
    """Main entry point for the budget application."""
    load_env_multi()
    logger = get_logger("budget")
    db_path = Path(DB_FILE)

    # Create GitHub sync service
    github_sync = GithubSync.from_env(db_path, logger=logger)

    # Initial database download
    initial_sha = None
    if github_sync:
        try:
            initial_sha = github_sync.download_db()
            logger.info("Startup: GitHub DB download successful, sha=%s", initial_sha)
        except Exception as e:
            logger.exception("Startup: GitHub download failed")
    else:
        logger.info("GitHub sync disabled - no token/owner/repo configured")

    # Create and run main application
    app = BudgetApp(github_sync=github_sync, initial_sha=initial_sha, logger=logger)
    app.mainloop()

if __name__ == "__main__":
    main()
