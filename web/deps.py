from services.env_loader import load_env_multi
from services.logging_config import get_logger

# Global instances
logger = None

def get_logger_service():
    """Get logger service."""
    global logger
    if logger is None:
        logger = get_logger("budget-web")
    return logger
