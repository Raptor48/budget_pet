import os
import sys
from pathlib import Path

def load_env_multi():
    """Load environment variables from multiple locations."""
    try:
        from dotenv import load_dotenv, find_dotenv
        # 1) Текущая рабочая папка
        load_dotenv()
        # 2) Папка исполняемого файла (.exe/.app)
        try:
            if getattr(sys, "frozen", False):
                exe_dir = Path(sys.executable).resolve().parent
                load_dotenv(exe_dir / ".env")
        except Exception:
            pass
        # 3) Папка рядом с локальной БД (removed - using PostgreSQL now)
        # This was for SQLite database location, no longer needed
        # 4) Поиск «вверх»
        try:
            env_path = find_dotenv(usecwd=True)
            if env_path:
                load_dotenv(env_path)
        except Exception:
            pass
    except Exception:
        pass
