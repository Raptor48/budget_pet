from services.env_loader import load_env_multi
from services.logging_config import get_logger
from services.github_sync import GithubSync
from bd import DB_FILE
from pathlib import Path
from typing import Optional

# Global instances
logger = None
github_sync = None

def get_logger_service():
    """Get logger service."""
    global logger
    if logger is None:
        logger = get_logger("budget-web")
    return logger

def get_github_sync():
    """Get GitHub sync service."""
    global github_sync
    if github_sync is None:
        db_path = Path(DB_FILE)
        logger = get_logger_service()
        github_sync = GithubSync.from_env(db_path, logger=logger)
        if github_sync:
            try:
                github_sync.download_db()
            except Exception:
                logger.exception("GitHub download failed")
    return github_sync
