import logging
from pathlib import Path
from bd import DB_FILE

LOG_FILE = Path(DB_FILE).with_name("app.log")

def get_logger(name: str) -> logging.Logger:
    """Get configured logger for the application."""
    logger = logging.getLogger(name)
    if logger.handlers:  # Already configured
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
